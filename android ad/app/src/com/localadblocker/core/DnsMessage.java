package com.localadblocker.core;

/** Reads the question in a DNS lookup and builds the "no such name" answer. Anything malformed is refused. */
public final class DnsMessage {
    private static final int HEADER_BYTES = 12;
    private static final int MAX_NAME_LENGTH = 255;
    private static final int MAX_LABEL_LENGTH = 63;
    private static final int TYPE_AND_CLASS_BYTES = 4;
    private static final int NO_SUCH_NAME = 3;

    private DnsMessage() {
    }

    /** The name being looked up, or null if this isn't one well-formed question. */
    public static String questionName(byte[] data, int offset, int length) {
        if (questionEnd(data, offset, length) < 0) {
            return null;
        }
        StringBuilder name = new StringBuilder();
        int position = offset + HEADER_BYTES;
        for (int size = data[position] & 0xFF; size != 0; size = data[position] & 0xFF) {
            if (name.length() > 0) {
                name.append('.');
            }
            for (int i = 1; i <= size; i++) {
                name.append((char) (data[position + i] & 0xFF));
            }
            position += size + 1;
        }
        return name.toString();
    }

    /** Where the question ends, or -1 if the message isn't one well-formed question. */
    private static int questionEnd(byte[] data, int offset, int length) {
        if (length < HEADER_BYTES + 1 + TYPE_AND_CLASS_BYTES) {
            return -1;
        }
        boolean isQuery = (data[offset + 2] & 0x80) == 0;
        boolean oneQuestion = data[offset + 4] == 0 && data[offset + 5] == 1;
        if (!isQuery || !oneQuestion) {
            return -1;
        }
        int end = offset + length;
        int position = offset + HEADER_BYTES;
        int nameLength = 0;
        while (true) {
            if (position >= end) {
                return -1;
            }
            int size = data[position] & 0xFF;
            if (size > MAX_LABEL_LENGTH) {
                return -1; // Includes compression pointers, which a question never needs.
            }
            position += size + 1;
            if (size == 0) {
                break;
            }
            nameLength += size + 1;
            if (nameLength > MAX_NAME_LENGTH) {
                return -1;
            }
        }
        position += TYPE_AND_CLASS_BYTES;
        return position <= end ? position : -1;
    }

    /** Tells the asking app that this name doesn't exist, so it gives up straight away. */
    public static byte[] noSuchName(byte[] data, int offset, int length) {
        int end = questionEnd(data, offset, length);
        if (end < 0) {
            throw new IllegalArgumentException("Not a well-formed lookup");
        }
        byte[] reply = new byte[end - offset];
        System.arraycopy(data, offset, reply, 0, reply.length);
        reply[2] = (byte) (0x80 | (data[offset + 2] & 0x01));
        reply[3] = (byte) (0x80 | NO_SUCH_NAME);
        for (int i = 6; i < HEADER_BYTES; i++) {
            reply[i] = 0;
        }
        return reply;
    }

    /** Whether a reply really belongs to this lookup. */
    public static boolean answersQuery(byte[] query, byte[] answer, int answerLength) {
        return answerLength >= HEADER_BYTES && query.length >= HEADER_BYTES
                && answer[0] == query[0] && answer[1] == query[1] && (answer[2] & 0x80) != 0;
    }
}
