package com.videosorter.app.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.NetworkInterface
import java.net.SocketTimeoutException
import java.util.Collections

/** 局域网里能连上的服务器。 */
data class FoundServer(
    val name: String,
    val ip: String,
    val port: Int,
    val version: String,
) {
    val address: String get() = "$ip:$port"
}

/**
 * 局域网自动发现：向 UDP 38080 广播 VS_DISCOVER，服务器回 JSON。
 * 不依赖 NSD/mDNS，纯 UDP，服务器端见 videosorter/discovery.py。
 */
object LanDiscovery {
    private const val PORT = 38080
    private val PROBE = "VS_DISCOVER".toByteArray(Charsets.UTF_8)

    suspend fun scan(timeoutMs: Long = 1600): List<FoundServer> = withContext(Dispatchers.IO) {
        val found = LinkedHashMap<String, FoundServer>()
        runCatching {
            DatagramSocket().use { sock ->
                sock.broadcast = true
                sock.soTimeout = 220
                val targets = LinkedHashSet<InetAddress>()
                runCatching { targets.add(InetAddress.getByName("255.255.255.255")) }
                runCatching { targets.add(InetAddress.getByName("127.0.0.1")) }
                // 广播地址未必被路由器转发，补上各网卡的定向广播地址
                runCatching {
                    Collections.list(NetworkInterface.getNetworkInterfaces()).forEach { nif ->
                        if (!nif.isUp || nif.isLoopback) return@forEach
                        nif.interfaceAddresses.forEach { addr ->
                            addr.broadcast?.let { targets.add(it) }
                        }
                    }
                }
                targets.forEach { t ->
                    runCatching { sock.send(DatagramPacket(PROBE, PROBE.size, t, PORT)) }
                }

                val deadline = System.currentTimeMillis() + timeoutMs
                val buf = ByteArray(2048)
                while (System.currentTimeMillis() < deadline) {
                    val pkt = DatagramPacket(buf, buf.size)
                    try {
                        sock.receive(pkt)
                    } catch (_: SocketTimeoutException) {
                        continue
                    }
                    val text = String(pkt.data, 0, pkt.length, Charsets.UTF_8)
                    val server = parseReply(text, pkt.address.hostAddress) ?: continue
                    found["${server.ip}:${server.port}"] = server
                }
            }
        }
        found.values.sortedBy { it.name }
    }
}

/**
 * 解析服务器回包。纯函数，方便单测：
 * ```json
 * {"app":"VideoSorter","version":"0.1.0","name":"VideoSorter @ fnos","port":8080,"ip":"192.168.1.8"}
 * ```
 * 不是 VideoSorter 的回包、或不是合法 JSON 时返回 null；ip 缺失时用发送方地址兜底。
 */
internal fun parseReply(text: String, senderHint: String? = null): FoundServer? {
    if (!text.contains("VideoSorter")) return null
    val obj = runCatching { Json.parseToJsonElement(text).jsonObject }.getOrNull() ?: return null
    val ip = obj["ip"]?.jsonPrimitive?.contentOrNull?.takeIf { it.isNotBlank() }
        ?: senderHint?.takeIf { it.isNotBlank() }
        ?: return null
    val port = obj["port"]?.jsonPrimitive?.contentOrNull?.toIntOrNull() ?: 8080
    if (port !in 1..65535) return null
    val name = obj["name"]?.jsonPrimitive?.contentOrNull ?: "VideoSorter"
    val ver = obj["version"]?.jsonPrimitive?.contentOrNull ?: ""
    return FoundServer(name, ip, port, ver)
}
