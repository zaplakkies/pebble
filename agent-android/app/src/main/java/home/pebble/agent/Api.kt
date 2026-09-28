package home.pebble.agent

import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

class ApiError(message: String, val status: Int? = null) : IOException(message)

/** The agent API (docs/api.md), over plain HttpURLConnection. */
object Api {
    fun normaliseServer(input: String): String {
        val s = input.trim().trimEnd('/')
        return if (s.startsWith("http://") || s.startsWith("https://")) s else "http://$s"
    }

    fun request(method: String, url: String, token: String?, installId: String?,
                body: String? = null): JSONObject {
        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 15_000
            readTimeout = 30_000
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("User-Agent", "pebble-agent-android/${BuildConfig.VERSION_NAME}")
            if (token != null) setRequestProperty("Authorization", "Bearer $token")
            if (installId != null) setRequestProperty("X-Pebble-Install-Id", installId)
        }
        try {
            if (body != null) {
                conn.doOutput = true
                conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
            val status = conn.responseCode
            if (status == 401) throw ApiError("the server does not recognise this device (token revoked?)", 401)
            if (status !in 200..299) throw ApiError("server returned HTTP $status", status)
            return JSONObject(conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() })
        } catch (e: ApiError) {
            throw e
        } catch (e: Exception) {
            throw ApiError("cannot reach the server: ${e.message ?: e.javaClass.simpleName}")
        } finally {
            conn.disconnect()
        }
    }

    data class Paired(val token: String, val device: String?, val kid: String?)

    fun pair(server: String, code: String): Paired {
        val digits = code.filter { it.isDigit() }
        if (digits.length != 6) throw ApiError("The pairing code has 6 digits.")
        try {
            val r = request("POST", "$server/api/v1/pair", null, null,
                JSONObject().put("code", digits).toString())
            return Paired(r.getString("token"), r.optString("device").ifEmpty { null },
                r.optString("kid").ifEmpty { null })
        } catch (e: ApiError) {
            if (e.status == 404) throw ApiError("The server does not recognise that code. Codes work " +
                "once and for 15 minutes; get a new one from the device page.", 404)
            throw e
        }
    }
}
