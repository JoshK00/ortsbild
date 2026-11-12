//
//  AuthViewModel.swift
//  Ortsbild
//

import AuthenticationServices
import CryptoKit
import SwiftUI

@MainActor
@Observable
final class AuthViewModel {
    private(set) var state: AuthState = .signedOut
    private(set) var isWorking = false
    private(set) var errorMessage: String?
    var isSheetPresented = false
    /// Called after the account was deleted, so the history on this phone can be removed too.
    var onAccountDeleted: (() -> Void)?

    private let service: AuthService
    /// Random value of the current sign-in. Apple gets only its SHA-256, the backend gets the value itself,
    /// so a stolen identity token cannot be used without it.
    private var rawNonce = ""

    init(service: AuthService? = nil) {
        let service = service ?? AppServices.auth
        self.service = service
        // TODO: Check `getCredentialState` at launch (the user may revoke Apple ID access in iOS settings)
        Task {
            if let reporter = await service.restoreSession() {
                state = .signedIn(reporter)
            }
        }
        // The backend ended the session for good (for example after a refresh token was reused)
        Task { [weak self] in
            for await _ in NotificationCenter.default.notifications(named: .backendSessionEnded) {
                self?.state = .signedOut
            }
        }
    }

    var isSignedIn: Bool {
        if case .signedIn = state { true } else { false }
    }

    var reporter: Reporter? {
        if case .signedIn(let reporter) = state { reporter } else { nil }
    }

    /// Request handler of `SignInWithAppleButton`: no name or e-mail, and the nonce.
    func prepare(_ request: ASAuthorizationAppleIDRequest) {
        request.requestedScopes = []
        rawNonce = Self.randomNonce()
        request.nonce = Self.sha256Hex(rawNonce)
    }

    /// Completion handler of `SignInWithAppleButton`.
    func handle(_ result: Result<ASAuthorization, Error>) {
        switch result {
        case .failure(let error):
            // The user cancelling the dialog is not an error worth showing.
            if (error as? ASAuthorizationError)?.code != .canceled {
                errorMessage = "Die Anmeldung ist fehlgeschlagen. Bitte versuche es erneut."
            }
        case .success(let authorization):
            guard let credential = authorization.credential as? ASAuthorizationAppleIDCredential,
                  let identityToken = credential.identityToken
            else {
                errorMessage = "Die Anmeldung ist fehlgeschlagen. Bitte versuche es erneut."
                return
            }
            signIn(identityToken: identityToken)
        }
    }

    func signOut() {
        Task {
            await service.signOut()
            state = .signedOut
        }
    }

    func deleteAccount() {
        isWorking = true
        errorMessage = nil
        Task {
            do {
                try await service.deleteAccount()
                onAccountDeleted?()
                state = .signedOut
            } catch {
                errorMessage = "Der Account konnte nicht gelöscht werden. Bitte versuche es erneut."
            }
            isWorking = false
        }
    }

    private func signIn(identityToken: Data) {
        isWorking = true
        errorMessage = nil
        let nonce = rawNonce
        Task {
            do {
                let reporter = try await service.signIn(identityToken: identityToken, nonce: nonce)
                state = .signedIn(reporter)
                isSheetPresented = false
            } catch {
                errorMessage = "Die Anmeldung ist fehlgeschlagen. Bitte versuche es erneut."
            }
            isWorking = false
        }
    }

    private static func randomNonce() -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        let status = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        precondition(status == errSecSuccess, "no secure random numbers available")
        return bytes.map { String(format: "%02x", $0) }.joined()
    }

    private static func sha256Hex(_ input: String) -> String {
        SHA256.hash(data: Data(input.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}
