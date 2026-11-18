package com.sintu.studio

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.nio.ByteBuffer
import java.nio.charset.StandardCharsets
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

/** Stores the SINTU session cookie encrypted and binds it to the server origin that issued it. */
class SecureSessionStore(context: Context) {
    private val preferences = context.getSharedPreferences("sintu_secure_session", Context.MODE_PRIVATE)

    fun save(value: String, origin: String) {
        require(origin.isNotBlank()) { "Session cookie origin must not be blank." }
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        val encrypted = cipher.doFinal(value.toByteArray(StandardCharsets.UTF_8))
        val payload = ByteBuffer.allocate(4 + cipher.iv.size + encrypted.size)
            .putInt(cipher.iv.size).put(cipher.iv).put(encrypted).array()
        preferences.edit()
            .putString(COOKIE_KEY, Base64.encodeToString(payload, Base64.NO_WRAP))
            .putString(ORIGIN_KEY, origin)
            .apply()
    }

    fun read(origin: String): String? {
        val encoded = preferences.getString(COOKIE_KEY, null) ?: return null
        if (origin.isBlank() || preferences.getString(ORIGIN_KEY, null) != origin) {
            clear()
            return null
        }
        return try {
            val payload = ByteBuffer.wrap(Base64.decode(encoded, Base64.NO_WRAP))
            require(payload.remaining() >= 4)
            val ivSize = payload.int
            require(ivSize in 12..16 && payload.remaining() > ivSize)
            val iv = ByteArray(ivSize).also(payload::get)
            val encrypted = ByteArray(payload.remaining()).also(payload::get)
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), javax.crypto.spec.GCMParameterSpec(128, iv))
            cipher.doFinal(encrypted).toString(StandardCharsets.UTF_8)
        } catch (_: Exception) {
            clear()
            null
        }
    }

    fun clear() {
        preferences.edit().remove(COOKIE_KEY).remove(ORIGIN_KEY).apply()
    }

    private fun getOrCreateKey(): SecretKey {
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build()
        )
        return generator.generateKey()
    }

    companion object {
        private const val KEY_ALIAS = "sintu_session_aes_v1"
        private const val COOKIE_KEY = "encrypted_session_cookie"
        private const val ORIGIN_KEY = "session_cookie_origin"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
    }
}
