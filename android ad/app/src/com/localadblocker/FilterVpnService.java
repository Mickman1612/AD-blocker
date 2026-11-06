package com.localadblocker;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.net.ConnectivityManager;
import android.net.LinkProperties;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.net.VpnService;
import android.os.Build;
import android.os.ParcelFileDescriptor;

import com.localadblocker.core.Blocklist;
import com.localadblocker.core.DnsMessage;
import com.localadblocker.core.FilterEngine;
import com.localadblocker.core.UdpPacket;

import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.SynchronousQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/**
 * Filters name lookups on this phone. Despite Android's name for the API this is not a real VPN:
 * nothing goes to an outside VPN server, and only lookups to a made-up DNS address enter the tunnel.
 * All other traffic goes to the network as normal.
 */
public class FilterVpnService extends VpnService {
    static final String ACTION_STOP = "com.localadblocker.STOP";

    private static final String CHANNEL = "filter";
    private static final int NOTIFICATION_ID = 1;
    private static final String TUNNEL_V4 = "10.111.222.1";
    private static final String DNS_V4 = "10.111.222.2";
    private static final String TUNNEL_V6 = "fd00:6164:626c::1";
    private static final String DNS_V6 = "fd00:6164:626c::2";
    private static final int MTU = 1500;
    private static final int DNS_PORT = 53;
    private static final int LOOKUP_TIMEOUT_MS = 2500;
    private static final int MAX_ANSWER_BYTES = 4096;
    private static final int MAX_LOOKUPS_AT_ONCE = 32;

    private static volatile FilterEngine activeEngine;
    private static volatile boolean running;

    private final Object writeLock = new Object();
    private final ThreadPoolExecutor lookups = new ThreadPoolExecutor(2, MAX_LOOKUPS_AT_ONCE, 30, TimeUnit.SECONDS,
            new SynchronousQueue<>(), new ThreadPoolExecutor.DiscardPolicy());

    private ParcelFileDescriptor tunnel;
    private Thread reader;

    /** Real networks only. The request below excludes VPNs, or lookups would be sent back into our own tunnel. */
    private final Map<Network, LinkProperties> realNetworks = new ConcurrentHashMap<>();

    private final ConnectivityManager.NetworkCallback networkWatcher = new ConnectivityManager.NetworkCallback() {
        @Override
        public void onLinkPropertiesChanged(Network network, LinkProperties properties) {
            realNetworks.put(network, properties);
        }

        @Override
        public void onLost(Network network) {
            realNetworks.remove(network);
        }
    };
    private boolean watchingNetwork;

    static boolean isRunning() {
        return running;
    }

    static long blockedCount() {
        FilterEngine engine = activeEngine;
        return engine == null ? 0 : engine.blockedCount();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            Settings.setEnabled(this, false);
            shutdown();
            stopSelf();
            return START_NOT_STICKY;
        }
        // Also reached with no extras when Android's Always-on VPN setting starts this.
        showNotification();
        if (!running && !startFiltering()) {
            Settings.setEnabled(this, false);
            shutdown();
            stopSelf();
            return START_NOT_STICKY;
        }
        Settings.setEnabled(this, true);
        return START_STICKY;
    }

    private boolean startFiltering() {
        try {
            activeEngine = new FilterEngine(loadLists());
        } catch (IOException error) {
            return false;
        }

        // Android's "default network" can be this app's own tunnel, so ask for real networks directly.
        ConnectivityManager connectivity = getSystemService(ConnectivityManager.class);
        connectivity.registerNetworkCallback(new NetworkRequest.Builder()
                .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                .addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
                .build(), networkWatcher);
        watchingNetwork = true;

        Builder builder = new Builder()
                .setSession(getString(R.string.app_name))
                .setMtu(MTU)
                .addAddress(TUNNEL_V4, 32)
                .addDnsServer(DNS_V4)
                .addRoute(DNS_V4, 32)
                .addAddress(TUNNEL_V6, 128)
                .addDnsServer(DNS_V6)
                .addRoute(DNS_V6, 128)
                .setBlocking(true);
        try {
            builder.addDisallowedApplication(getPackageName());
            // Also needed when Android restarts this service by itself: it makes this app the active VPN.
            if (VpnService.prepare(this) != null) {
                return false; // The user took back the VPN permission.
            }
            tunnel = builder.establish();
        } catch (PackageManager.NameNotFoundException | IllegalStateException | SecurityException error) {
            return false;
        }
        if (tunnel == null) {
            return false;
        }
        running = true;
        reader = new Thread(this::readLoop, "filter");
        reader.start();
        return true;
    }

    private Blocklist loadLists() throws IOException {
        try (InputStreamReader block = new InputStreamReader(getAssets().open("blocklist.txt"), StandardCharsets.US_ASCII);
             InputStreamReader allow = new InputStreamReader(getAssets().open("allowlist.txt"), StandardCharsets.US_ASCII)) {
            return Blocklist.read(block, allow);
        }
    }

    private void readLoop() {
        byte[] buffer = new byte[MTU + 100];
        FilterEngine engine = activeEngine;
        try (FileInputStream in = new FileInputStream(tunnel.getFileDescriptor());
             FileOutputStream out = new FileOutputStream(tunnel.getFileDescriptor())) {
            while (running) {
                int length = in.read(buffer);
                if (length <= 0) {
                    continue;
                }
                FilterEngine.Decision decision = engine.decide(buffer, length);
                if (decision.action == FilterEngine.Action.REPLY) {
                    write(out, decision.reply);
                } else if (decision.action == FilterEngine.Action.FORWARD) {
                    UdpPacket packet = decision.packet;
                    lookups.execute(() -> forward(packet, out));
                }
            }
        } catch (IOException error) {
            // The tunnel closed, which is how the filter stops.
        }
    }

    private void write(FileOutputStream out, byte[] packet) throws IOException {
        synchronized (writeLock) {
            out.write(packet);
        }
    }

    /** Ask the phone's own DNS server, the one it would use without this app. No other server is ever used. */
    private void forward(UdpPacket request, FileOutputStream out) {
        byte[] query = request.copyPayload();
        Network network = bestNetwork();
        LinkProperties properties = network == null ? null : realNetworks.get(network);
        if (properties == null) {
            return;
        }
        for (InetAddress server : properties.getDnsServers()) {
            try (DatagramSocket socket = new DatagramSocket()) {
                protect(socket);
                network.bindSocket(socket);
                socket.setSoTimeout(LOOKUP_TIMEOUT_MS);
                socket.send(new DatagramPacket(query, query.length, server, DNS_PORT));
                byte[] answer = new byte[MAX_ANSWER_BYTES];
                DatagramPacket received = new DatagramPacket(answer, answer.length);
                socket.receive(received);
                if (received.getAddress().equals(server)
                        && DnsMessage.answersQuery(query, answer, received.getLength())) {
                    byte[] exact = new byte[received.getLength()];
                    System.arraycopy(answer, 0, exact, 0, exact.length);
                    write(out, request.buildReply(exact));
                    return;
                }
            } catch (IOException error) {
                // No answer from this server, so try the next one.
            }
        }
    }

    /** The network Android would use anyway: one with working internet, preferring Wi-Fi or a cable. */
    private Network bestNetwork() {
        ConnectivityManager connectivity = getSystemService(ConnectivityManager.class);
        Network best = null;
        int bestScore = -1;
        for (Network network : realNetworks.keySet()) {
            NetworkCapabilities capabilities = connectivity.getNetworkCapabilities(network);
            if (capabilities == null) {
                continue;
            }
            int score = 0;
            if (capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)) {
                score += 2;
            }
            if (capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
                    || capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)) {
                score += 1;
            }
            if (score > bestScore) {
                best = network;
                bestScore = score;
            }
        }
        return best;
    }

    private void showNotification() {
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL, getString(R.string.notification_channel),
                NotificationManager.IMPORTANCE_LOW));
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class),
                PendingIntent.FLAG_IMMUTABLE);
        Notification notification = new Notification.Builder(this, CHANNEL)
                .setSmallIcon(R.drawable.ic_notification)
                .setContentTitle(getString(R.string.notification_title))
                .setContentText(getString(R.string.notification_text))
                .setContentIntent(open)
                .setOngoing(true)
                .build();
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SYSTEM_EXEMPTED);
        } else {
            startForeground(NOTIFICATION_ID, notification);
        }
    }

    private void shutdown() {
        running = false;
        if (watchingNetwork) {
            getSystemService(ConnectivityManager.class).unregisterNetworkCallback(networkWatcher);
            watchingNetwork = false;
            realNetworks.clear();
        }
        if (tunnel != null) {
            try {
                tunnel.close();
            } catch (IOException error) {
                // Already closed.
            }
            tunnel = null;
        }
        if (reader != null) {
            reader.interrupt();
            reader = null;
        }
        activeEngine = null;
        stopForeground(STOP_FOREGROUND_REMOVE);
    }

    @Override
    public void onRevoke() {
        // Another VPN started, or the user turned this off in Android's settings.
        Settings.setEnabled(this, false);
        shutdown();
        stopSelf();
        super.onRevoke();
    }

    @Override
    public void onDestroy() {
        shutdown();
        lookups.shutdownNow();
        super.onDestroy();
    }

    static Intent stopIntent(Context context) {
        return new Intent(context, FilterVpnService.class).setAction(ACTION_STOP);
    }
}
