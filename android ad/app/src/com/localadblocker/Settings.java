package com.localadblocker;

import android.content.Context;

/** Remembers on this phone whether the user turned the filter on. Nothing else is stored. */
final class Settings {
    private static final String FILE = "settings";
    private static final String ENABLED = "enabled";

    private Settings() {
    }

    static boolean isEnabled(Context context) {
        return context.getSharedPreferences(FILE, Context.MODE_PRIVATE).getBoolean(ENABLED, false);
    }

    static void setEnabled(Context context, boolean enabled) {
        context.getSharedPreferences(FILE, Context.MODE_PRIVATE).edit().putBoolean(ENABLED, enabled).apply();
    }
}
