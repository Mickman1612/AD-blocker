package com.localadblocker.core;

import java.util.concurrent.atomic.AtomicLong;

/** Decides what happens to each packet that comes out of the tunnel. */
public final class FilterEngine {
    private static final int DNS_PORT = 53;

    public enum Action {
        /** Send {@link Decision#reply} straight back to the asking app. */
        REPLY,
        /** Ask the phone's real DNS server and send the answer back. */
        FORWARD,
        /** Not a lookup we can read, so ignore it. */
        DROP
    }

    public static final class Decision {
        private static final Decision IGNORED = new Decision(Action.DROP, null, null);

        public final Action action;
        public final byte[] reply;
        public final UdpPacket packet;

        private Decision(Action action, byte[] reply, UdpPacket packet) {
            this.action = action;
            this.reply = reply;
            this.packet = packet;
        }
    }

    private final Blocklist list;
    private final AtomicLong blocked = new AtomicLong();

    public FilterEngine(Blocklist list) {
        this.list = list;
    }

    public Decision decide(byte[] data, int length) {
        UdpPacket packet = UdpPacket.parse(data, length);
        if (packet == null || packet.destinationPort() != DNS_PORT) {
            return Decision.IGNORED;
        }
        byte[] query = packet.copyPayload();
        String name = DnsMessage.questionName(query, 0, query.length);
        if (name == null) {
            return Decision.IGNORED;
        }
        if (list.isBlocked(name)) {
            blocked.incrementAndGet();
            return new Decision(Action.REPLY, packet.buildReply(DnsMessage.noSuchName(query, 0, query.length)), null);
        }
        return new Decision(Action.FORWARD, null, packet);
    }

    public long blockedCount() {
        return blocked.get();
    }
}
