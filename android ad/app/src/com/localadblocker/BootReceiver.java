package com.localadblocker;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.net.VpnService;

/** Starts the filter again after the phone restarts, if the user had it on. */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent.getAction();
        boolean started = Intent.ACTION_BOOT_COMPLETED.equals(action) || Intent.ACTION_MY_PACKAGE_REPLACED.equals(action);
        // prepare() returning null means Android still has the user's VPN permission for this app.
        if (started && Settings.isEnabled(context) && VpnService.prepare(context) == null) {
            context.startForegroundService(new Intent(context, FilterVpnService.class));
        }
    }
}
