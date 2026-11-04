//
//  SessionStore.swift
//  Ortsbild
//

import Foundation
import Security

/// The session the backend gave us after the Sign in with Apple. Short access token, long refresh token.
nonisolated struct Session: Codable, Equatable, Sendable {
    var accessToken: String
    var refreshToken: String
    var expiresAt: Date
    /// Shortened pseudonymous user id from the backend (`reporter_id`), never the Apple id.
    var reporterID: String
}

/// Keeps the session in the Keychain, so it survives a restart and no other app can read it.
nonisolated struct SessionStore: Sendable {
    private let service = "com.Joshua-Kehrer.Ortsbild.session"
    private let account = "backend-session"

    func load() -> Session? {
        var query = baseQuery
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data
        else { return nil }
        return try? JSONDecoder().decode(Session.self, from: data)
    }

    func save(_ session: Session) {
        guard let data = try? JSONEncoder().encode(session) else { return }
        let update = [kSecValueData as String: data]
        if SecItemUpdate(baseQuery as CFDictionary, update as CFDictionary) == errSecItemNotFound {
            var add = baseQuery
            add[kSecValueData as String] = data
            // Readable after the first unlock, and never copied to another device or a backup.
            add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            SecItemAdd(add as CFDictionary, nil)
        }
    }

    func clear() {
        SecItemDelete(baseQuery as CFDictionary)
    }

    private var baseQuery: [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }
}
