package com.localadblocker.core;

/** A UDP packet read from the tunnel, keeping its own copy of the data. Handles IPv4 and IPv6. */
public final class UdpPacket {
    private static final int IPV4_MIN_HEADER = 20;
    private static final int IPV6_HEADER = 40;
    private static final int UDP_HEADER = 8;
    private static final int PROTOCOL_UDP = 17;
    private static final int HOP_LIMIT = 64;

    private final int version;
    private final byte[] source;
    private final byte[] destination;
    private final int sourcePort;
    private final int destinationPort;
    private final byte[] payload;

    private UdpPacket(int version, byte[] source, byte[] destination, int sourcePort, int destinationPort, byte[] payload) {
        this.version = version;
        this.source = source;
        this.destination = destination;
        this.sourcePort = sourcePort;
        this.destinationPort = destinationPort;
        this.payload = payload;
    }

    /** Returns null for anything that isn't a complete, unfragmented UDP packet. */
    public static UdpPacket parse(byte[] data, int length) {
        if (length < 1) {
            return null;
        }
        int version = (data[0] & 0xF0) >> 4;
        if (version == 4) {
            return parseV4(data, length);
        }
        return version == 6 ? parseV6(data, length) : null;
    }

    private static UdpPacket parseV4(byte[] data, int length) {
        if (length < IPV4_MIN_HEADER + UDP_HEADER) {
            return null;
        }
        int headerLength = (data[0] & 0x0F) * 4;
        int total = word(data, 2);
        boolean fragment = (data[6] & 0x20) != 0 || (data[6] & 0x1F) != 0 || data[7] != 0;
        if (headerLength < IPV4_MIN_HEADER || total > length || total < headerLength + UDP_HEADER
                || data[9] != PROTOCOL_UDP || fragment) {
            return null;
        }
        return read(4, data, 12, 16, 4, headerLength, total);
    }

    private static UdpPacket parseV6(byte[] data, int length) {
        if (length < IPV6_HEADER + UDP_HEADER || data[6] != PROTOCOL_UDP) {
            return null; // Extension headers aren't used by normal DNS lookups.
        }
        int total = IPV6_HEADER + word(data, 4);
        if (total > length || total < IPV6_HEADER + UDP_HEADER) {
            return null;
        }
        return read(6, data, 8, 24, 16, IPV6_HEADER, total);
    }

    private static UdpPacket read(int version, byte[] data, int sourceAt, int destinationAt, int addressBytes, int udpAt, int total) {
        int udpLength = word(data, udpAt + 4);
        if (udpLength < UDP_HEADER || udpAt + udpLength > total) {
            return null;
        }
        return new UdpPacket(version, slice(data, sourceAt, addressBytes), slice(data, destinationAt, addressBytes),
                word(data, udpAt), word(data, udpAt + 2), slice(data, udpAt + UDP_HEADER, udpLength - UDP_HEADER));
    }

    private static byte[] slice(byte[] data, int start, int count) {
        byte[] copy = new byte[count];
        System.arraycopy(data, start, copy, 0, count);
        return copy;
    }

    private static int word(byte[] data, int at) {
        return ((data[at] & 0xFF) << 8) | (data[at + 1] & 0xFF);
    }

    private static void putWord(byte[] data, int at, int value) {
        data[at] = (byte) (value >> 8);
        data[at + 1] = (byte) value;
    }

    public int sourcePort() {
        return sourcePort;
    }

    public int destinationPort() {
        return destinationPort;
    }

    public int payloadLength() {
        return payload.length;
    }

    public byte[] copyPayload() {
        return payload.clone();
    }

    /** A packet going back the other way, carrying this payload. */
    public byte[] buildReply(byte[] answer) {
        return version == 4 ? buildV4(answer) : buildV6(answer);
    }

    private byte[] buildV4(byte[] answer) {
        int total = IPV4_MIN_HEADER + UDP_HEADER + answer.length;
        byte[] out = new byte[total];
        out[0] = 0x45;
        putWord(out, 2, total);
        out[6] = 0x40; // Don't fragment.
        out[8] = HOP_LIMIT;
        out[9] = PROTOCOL_UDP;
        System.arraycopy(destination, 0, out, 12, 4);
        System.arraycopy(source, 0, out, 16, 4);
        putWord(out, 10, checksum(out, 0, IPV4_MIN_HEADER, 0));
        writeUdp(out, IPV4_MIN_HEADER, answer, 12, 8);
        return out;
    }

    private byte[] buildV6(byte[] answer) {
        byte[] out = new byte[IPV6_HEADER + UDP_HEADER + answer.length];
        out[0] = 0x60;
        putWord(out, 4, UDP_HEADER + answer.length);
        out[6] = PROTOCOL_UDP;
        out[7] = HOP_LIMIT;
        System.arraycopy(destination, 0, out, 8, 16);
        System.arraycopy(source, 0, out, 24, 16);
        writeUdp(out, IPV6_HEADER, answer, 8, 32);
        return out;
    }

    private void writeUdp(byte[] out, int udpAt, byte[] answer, int addressesAt, int addressBytes) {
        int udpLength = UDP_HEADER + answer.length;
        putWord(out, udpAt, destinationPort);
        putWord(out, udpAt + 2, sourcePort);
        putWord(out, udpAt + 4, udpLength);
        System.arraycopy(answer, 0, out, udpAt + UDP_HEADER, answer.length);
        long pseudoHeader = PROTOCOL_UDP + (long) udpLength + rawSum(out, addressesAt, addressesAt + addressBytes, 0);
        int value = checksum(out, udpAt, udpAt + udpLength, pseudoHeader);
        putWord(out, udpAt + 6, value == 0 ? 0xFFFF : value); // In UDP, a checksum of 0 means "none".
    }

    private static int checksum(byte[] data, int start, int end, long initial) {
        return ~fold(rawSum(data, start, end, initial)) & 0xFFFF;
    }

    private static long rawSum(byte[] data, int start, int end, long initial) {
        long total = initial;
        for (int i = start; i < end; i += 2) {
            int high = data[i] & 0xFF;
            int low = i + 1 < end ? data[i + 1] & 0xFF : 0;
            total += (high << 8) | low;
        }
        return total;
    }

    private static int fold(long total) {
        long folded = total;
        while ((folded >> 16) != 0) {
            folded = (folded & 0xFFFF) + (folded >> 16);
        }
        return (int) folded;
    }
}
