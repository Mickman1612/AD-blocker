package com.localadblocker.core;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.Reader;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

/** Decides whether a name is an ad server. Listing a domain also covers all its subdomains. */
public final class Blocklist {
    private final Set<String> blocked;
    private final Set<String> allowed;

    private Blocklist(Set<String> blocked, Set<String> allowed) {
        this.blocked = blocked;
        this.allowed = allowed;
    }

    public static Blocklist read(Reader blockedNames, Reader allowedNames) throws IOException {
        return new Blocklist(readNames(blockedNames), readNames(allowedNames));
    }

    private static Set<String> readNames(Reader source) throws IOException {
        Set<String> names = new HashSet<>();
        BufferedReader lines = new BufferedReader(source);
        for (String line = lines.readLine(); line != null; line = lines.readLine()) {
            String name = line.trim().toLowerCase(Locale.ROOT);
            if (!name.isEmpty() && !name.startsWith("#")) {
                names.add(name);
            }
        }
        return names;
    }

    public boolean isBlocked(String rawName) {
        String name = rawName.toLowerCase(Locale.ROOT);
        if (name.endsWith(".")) {
            name = name.substring(0, name.length() - 1);
        }
        return !name.isEmpty() && !listed(allowed, name) && listed(blocked, name);
    }

    private static boolean listed(Set<String> names, String name) {
        String current = name;
        while (true) {
            if (names.contains(current)) {
                return true;
            }
            int dot = current.indexOf('.');
            if (dot < 0) {
                return false;
            }
            current = current.substring(dot + 1);
        }
    }

    public int size() {
        return blocked.size();
    }
}
