import com.localadblocker.core.Blocklist;
import com.localadblocker.core.DnsMessage;
import com.localadblocker.core.FilterEngine;
import com.localadblocker.core.UdpPacket;

import java.io.ByteArrayOutputStream;
import java.io.StringReader;
import java.util.Arrays;

/** The packet logic, tested on the PC with no Android and no test library. Run by build.py. */
public class CoreTests {
    private static int passed;
    private static int failed;

    private static final byte[] PHONE_V4 = {10, 111, (byte) 222, 1};
    private static final byte[] DNS_V4 = {10, 111, (byte) 222, 2};
    private static final byte[] PHONE_V6 = v6(1);
    private static final byte[] DNS_V6 = v6(2);

    public static void main(String[] args) throws Exception {
        blocklistTests();
        dnsTests();
        packetTests();
        engineTests();
        System.out.println(passed + " passed, " + failed + " failed");
        if (failed > 0) {
            System.exit(1);
        }
    }

    // --- Blocklist ---

    private static Blocklist list() throws Exception {
        return Blocklist.read(new StringReader("doubleclick.net\nads.example.org\n"),
                new StringReader("static.doubleclick.net\n"));
    }

    private static void blocklistTests() throws Exception {
        Blocklist list = list();
        check("blocks a listed domain", list.isBlocked("doubleclick.net"));
        check("blocks a subdomain", list.isBlocked("securepubads.g.doubleclick.net"));
        check("ignores letter case", list.isBlocked("SecurePubAds.G.DoubleClick.NET"));
        check("ignores a trailing dot", list.isBlocked("doubleclick.net."));
        check("leaves other names alone", !list.isBlocked("www.youtube.com"));
        check("isn't fooled by a similar ending", !list.isBlocked("notdoubleclick.net"));
        check("doesn't block a listed name's parent", !list.isBlocked("example.org"));
        check("the allowlist wins", !list.isBlocked("static.doubleclick.net"));
        check("the allowlist covers subdomains", !list.isBlocked("a.static.doubleclick.net"));
        check("empty names aren't blocked", !list.isBlocked(""));
        check("counts its entries", list.size() == 2);
        Blocklist commented = Blocklist.read(new StringReader("# note\n\n  a.example.org  \n"), new StringReader(""));
        check("skips comments and blanks", commented.size() == 1 && commented.isBlocked("a.example.org"));
    }

    // --- DNS messages ---

    private static byte[] query(String name, int type) throws Exception {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        out.write(new byte[] {0x12, 0x34, 0x01, 0x00, 0, 1, 0, 0, 0, 0, 0, 0});
        for (String label : name.split("\\.")) {
            out.write(label.length());
            out.write(label.getBytes("US-ASCII"));
        }
        out.write(0);
        out.write(new byte[] {0, (byte) type, 0, 1});
        return out.toByteArray();
    }

    private static void dnsTests() throws Exception {
        byte[] request = query("ads.example.org", 1);
        check("reads the question name", "ads.example.org".equals(DnsMessage.questionName(request, 0, request.length)));
        check("rejects a too-short message", DnsMessage.questionName(new byte[5], 0, 5) == null);

        byte[] answer = request.clone();
        answer[2] |= (byte) 0x80;
        check("rejects a message that's already an answer", DnsMessage.questionName(answer, 0, answer.length) == null);

        byte[] noQuestion = request.clone();
        noQuestion[5] = 0;
        check("rejects a message with no question", DnsMessage.questionName(noQuestion, 0, noQuestion.length) == null);

        byte[] pointer = {0x12, 0x34, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, (byte) 0xC0, 0x0C, 0, 1, 0, 1};
        check("rejects a compressed question", DnsMessage.questionName(pointer, 0, pointer.length) == null);

        byte[] overrun = {0x12, 0x34, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 60, 'a', 'b'};
        check("rejects a label running past the end", DnsMessage.questionName(overrun, 0, overrun.length) == null);

        byte[] truncated = Arrays.copyOf(request, request.length - 2);
        check("rejects a question missing its type", DnsMessage.questionName(truncated, 0, truncated.length) == null);

        byte[] reply = DnsMessage.noSuchName(request, 0, request.length);
        check("answer keeps the query's id", reply[0] == 0x12 && reply[1] == 0x34);
        check("answer is marked as a response", (reply[2] & 0x80) != 0);
        check("answer keeps recursion-desired", (reply[2] & 0x01) != 0);
        check("answer says no such name", (reply[3] & 0x0F) == 3);
        check("answer repeats one question", reply[4] == 0 && reply[5] == 1);
        check("answer has no records", reply[7] == 0 && reply[9] == 0 && reply[11] == 0);
        check("answer ends with the question", reply.length == request.length
                && Arrays.equals(Arrays.copyOfRange(reply, 12, reply.length), Arrays.copyOfRange(request, 12, request.length)));

        check("a matching answer is accepted", DnsMessage.answersQuery(request, reply, reply.length));
        byte[] wrongId = reply.clone();
        wrongId[1] = 0x35;
        check("an answer with another id is refused", !DnsMessage.answersQuery(request, wrongId, wrongId.length));
        check("a query isn't accepted as an answer", !DnsMessage.answersQuery(request, request, request.length));
        check("a too-short answer is refused", !DnsMessage.answersQuery(request, reply, 6));

        byte[] withEdns = Arrays.copyOf(request, request.length + 11);
        withEdns[11] = 1;
        byte[] ednsReply = DnsMessage.noSuchName(withEdns, 0, withEdns.length);
        check("answer drops extra records from the query", ednsReply.length == request.length && ednsReply[11] == 0);
    }

    // --- IP and UDP packets ---

    private static byte[] udpV4(byte[] payload) {
        int total = 20 + 8 + payload.length;
        byte[] p = new byte[total];
        p[0] = 0x45;
        p[2] = (byte) (total >> 8);
        p[3] = (byte) total;
        p[8] = 64;
        p[9] = 17;
        System.arraycopy(PHONE_V4, 0, p, 12, 4);
        System.arraycopy(DNS_V4, 0, p, 16, 4);
        p[20] = (byte) 0xC3;
        p[21] = 0x50;
        p[23] = 53;
        p[24] = (byte) ((8 + payload.length) >> 8);
        p[25] = (byte) (8 + payload.length);
        System.arraycopy(payload, 0, p, 28, payload.length);
        return p;
    }

    private static byte[] udpV6(byte[] payload) {
        int total = 40 + 8 + payload.length;
        byte[] p = new byte[total];
        p[0] = 0x60;
        p[4] = (byte) ((8 + payload.length) >> 8);
        p[5] = (byte) (8 + payload.length);
        p[6] = 17;
        p[7] = 64;
        System.arraycopy(PHONE_V6, 0, p, 8, 16);
        System.arraycopy(DNS_V6, 0, p, 24, 16);
        p[40] = (byte) 0xC3;
        p[41] = 0x50;
        p[43] = 53;
        p[44] = (byte) ((8 + payload.length) >> 8);
        p[45] = (byte) (8 + payload.length);
        System.arraycopy(payload, 0, p, 48, payload.length);
        return p;
    }

    private static byte[] v6(int last) {
        byte[] address = new byte[16];
        address[0] = (byte) 0xFD;
        address[15] = (byte) last;
        return address;
    }

    /** One's-complement sum of 16-bit words. A correct checksummed block totals 0xFFFF. */
    private static int sum(byte[] data, int start, int end, long initial) {
        long total = initial;
        for (int i = start; i < end; i += 2) {
            int high = data[i] & 0xFF;
            int low = i + 1 < end ? data[i + 1] & 0xFF : 0;
            total += (high << 8) | low;
        }
        while ((total >> 16) != 0) {
            total = (total & 0xFFFF) + (total >> 16);
        }
        return (int) total;
    }

    private static void packetTests() throws Exception {
        byte[] payload = query("a.example.org", 1);

        byte[] v4 = udpV4(payload);
        UdpPacket parsed4 = UdpPacket.parse(v4, v4.length);
        check("reads an IPv4 UDP packet", parsed4 != null && parsed4.destinationPort() == 53 && parsed4.sourcePort() == 0xC350);
        check("finds the IPv4 payload", parsed4 != null && parsed4.payloadLength() == payload.length
                && Arrays.equals(parsed4.copyPayload(), payload));

        byte[] v6 = udpV6(payload);
        UdpPacket parsed6 = UdpPacket.parse(v6, v6.length);
        check("reads an IPv6 UDP packet", parsed6 != null && parsed6.destinationPort() == 53);
        check("finds the IPv6 payload", parsed6 != null && Arrays.equals(parsed6.copyPayload(), payload));

        byte[] tcp = v4.clone();
        tcp[9] = 6;
        check("ignores TCP", UdpPacket.parse(tcp, tcp.length) == null);
        byte[] fragment = v4.clone();
        fragment[6] = 0x20;
        check("ignores fragments", UdpPacket.parse(fragment, fragment.length) == null);
        check("ignores a short packet", UdpPacket.parse(new byte[10], 10) == null);
        check("ignores an unknown IP version", UdpPacket.parse(new byte[40], 40) == null);
        byte[] lying = v4.clone();
        lying[25] = (byte) 200;
        check("ignores a UDP length past the packet's end", UdpPacket.parse(lying, lying.length) == null);
        byte[] options = v4.clone();
        options[0] = 0x4F;
        check("ignores a header longer than the packet", UdpPacket.parse(options, 30) == null);

        byte[] answer = {1, 2, 3, 4, 5};
        byte[] reply4 = parsed4.buildReply(answer);
        UdpPacket back4 = UdpPacket.parse(reply4, reply4.length);
        check("IPv4 reply swaps ports", back4 != null && back4.sourcePort() == 53 && back4.destinationPort() == 0xC350);
        check("IPv4 reply swaps addresses", Arrays.equals(Arrays.copyOfRange(reply4, 12, 16), DNS_V4)
                && Arrays.equals(Arrays.copyOfRange(reply4, 16, 20), PHONE_V4));
        check("IPv4 reply carries the answer", back4 != null && Arrays.equals(back4.copyPayload(), answer));
        check("IPv4 header checksum is valid", sum(reply4, 0, 20, 0) == 0xFFFF);
        long pseudo4 = 17 + (reply4.length - 20);
        pseudo4 += sum(reply4, 12, 20, 0);
        check("IPv4 UDP checksum is valid", sum(reply4, 20, reply4.length, pseudo4) == 0xFFFF);

        byte[] reply6 = parsed6.buildReply(answer);
        UdpPacket back6 = UdpPacket.parse(reply6, reply6.length);
        check("IPv6 reply swaps ports", back6 != null && back6.sourcePort() == 53);
        check("IPv6 reply swaps addresses", Arrays.equals(Arrays.copyOfRange(reply6, 8, 24), DNS_V6)
                && Arrays.equals(Arrays.copyOfRange(reply6, 24, 40), PHONE_V6));
        long pseudo6 = 17 + (reply6.length - 40);
        pseudo6 += sum(reply6, 8, 40, 0);
        check("IPv6 UDP checksum is valid", sum(reply6, 40, reply6.length, pseudo6) == 0xFFFF);
    }

    // --- The decision for each packet ---

    private static void engineTests() throws Exception {
        FilterEngine engine = new FilterEngine(list());

        byte[] blocked = udpV4(query("securepubads.g.doubleclick.net", 1));
        FilterEngine.Decision first = engine.decide(blocked, blocked.length);
        check("blocked name gets an immediate reply", first.action == FilterEngine.Action.REPLY && first.reply != null);
        UdpPacket reply = UdpPacket.parse(first.reply, first.reply.length);
        check("the reply says no such name", reply != null && (reply.copyPayload()[3] & 0x0F) == 3);
        check("counts what it blocks", engine.blockedCount() == 1);

        byte[] allowed = udpV6(query("www.youtube.com", 28));
        FilterEngine.Decision second = engine.decide(allowed, allowed.length);
        check("other names are forwarded", second.action == FilterEngine.Action.FORWARD);
        check("forwarding keeps the exact query", Arrays.equals(second.packet.copyPayload(), query("www.youtube.com", 28)));
        check("forwarding isn't counted as blocked", engine.blockedCount() == 1);

        byte[] allowlisted = udpV4(query("static.doubleclick.net", 1));
        check("allowlisted names are forwarded", engine.decide(allowlisted, allowlisted.length).action == FilterEngine.Action.FORWARD);

        byte[] notDns = udpV4(query("a.example.org", 1));
        notDns[23] = 54;
        check("other ports are dropped", engine.decide(notDns, notDns.length).action == FilterEngine.Action.DROP);

        byte[] garbage = udpV4(new byte[] {1, 2, 3});
        check("malformed lookups are dropped", engine.decide(garbage, garbage.length).action == FilterEngine.Action.DROP);

        byte[] tcp = udpV4(query("a.example.org", 1));
        tcp[9] = 6;
        check("non-UDP traffic is dropped", engine.decide(tcp, tcp.length).action == FilterEngine.Action.DROP);
    }

    private static void check(String name, boolean condition) {
        if (condition) {
            passed++;
        } else {
            failed++;
            System.out.println("FAILED: " + name);
        }
    }
}
