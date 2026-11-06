package com.localadblocker;

import android.app.Activity;
import android.content.Intent;
import android.net.ConnectivityManager;
import android.net.LinkProperties;
import android.net.Network;
import android.net.VpnService;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.Button;
import android.widget.Switch;
import android.widget.TextView;

import java.text.NumberFormat;

/** One screen: an on/off switch, what it has blocked and a shortcut to Always-on VPN. */
public class MainActivity extends Activity {
    private static final int REQUEST_VPN_PERMISSION = 1;
    private static final long REFRESH_MS = 1000;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable refresher = new Runnable() {
        @Override
        public void run() {
            refresh();
            handler.postDelayed(this, REFRESH_MS);
        }
    };

    private Switch toggle;
    private TextView status;
    private TextView count;
    private TextView warning;
    private boolean updating;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        setContentView(R.layout.activity_main);
        toggle = findViewById(R.id.toggle);
        status = findViewById(R.id.status);
        count = findViewById(R.id.count);
        warning = findViewById(R.id.warning);
        Button alwaysOn = findViewById(R.id.always_on);

        toggle.setOnCheckedChangeListener((view, checked) -> {
            if (!updating) {
                if (checked) {
                    turnOn();
                } else {
                    startService(FilterVpnService.stopIntent(this));
                }
            }
        });
        alwaysOn.setOnClickListener(view -> startActivity(new Intent(android.provider.Settings.ACTION_VPN_SETTINGS)));
    }

    private void turnOn() {
        Intent permission = VpnService.prepare(this);
        if (permission != null) {
            startActivityForResult(permission, REQUEST_VPN_PERMISSION);
        } else {
            startFilter();
        }
    }

    private void startFilter() {
        startForegroundService(new Intent(this, FilterVpnService.class));
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == REQUEST_VPN_PERMISSION && result == RESULT_OK) {
            startFilter();
        }
        refresh();
    }

    @Override
    protected void onResume() {
        super.onResume();
        handler.post(refresher);
        warning.setVisibility(privateDnsMayBypass() ? View.VISIBLE : View.GONE);
    }

    @Override
    protected void onPause() {
        handler.removeCallbacks(refresher);
        super.onPause();
    }

    private void refresh() {
        boolean on = FilterVpnService.isRunning();
        updating = true;
        toggle.setChecked(on);
        updating = false;
        status.setText(on ? R.string.status_on : R.string.status_off);
        count.setVisibility(on ? View.VISIBLE : View.INVISIBLE);
        count.setText(getString(R.string.blocked_count,
                NumberFormat.getIntegerInstance().format(FilterVpnService.blockedCount())));
    }

    /** A Private DNS provider chosen in Settings can send lookups around the filter. */
    private boolean privateDnsMayBypass() {
        if (Build.VERSION.SDK_INT < 28) {
            return false;
        }
        ConnectivityManager connectivity = getSystemService(ConnectivityManager.class);
        Network network = connectivity.getActiveNetwork();
        LinkProperties properties = network == null ? null : connectivity.getLinkProperties(network);
        return properties != null && properties.getPrivateDnsServerName() != null;
    }
}
