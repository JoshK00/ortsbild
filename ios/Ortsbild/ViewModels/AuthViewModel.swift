//
//  AuthViewModel.swift
//  Ortsbild
//

import AuthenticationServices
import SwiftUI

@MainActor
@Observable
final class AuthViewModel {
    private(set) var state: AuthState = .signedOut
    private(set) var isWorking = false
    private(set) var errorMessage: String?
    var isSheetPresented = false

    private let service: AuthService

    init(service: AuthService = MockAuthService()) {
        self.service = service
        // TODO: Restore the session from the Keychain and check `getCredentialState` at launch (the user may revoke Apple ID access in iOS settings)
    }

    var isSignedIn: Bool {
        if case .signedIn = state { true } else { false }
    }

    var reporter: Reporter? {
        if case .signedIn(let reporter) = state { reporter } else { nil }
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
                  let identityToken = credential.identityToken,
                  let authorizationCode = credential.authorizationCode
            else {
                errorMessage = "Die Anmeldung ist fehlgeschlagen. Bitte versuche es erneut."
                return
            }
            signIn(identityToken: identityToken, authorizationCode: authorizationCode)
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
                state = .signedOut
            } catch {
                errorMessage = "Der Account konnte nicht gelöscht werden. Bitte versuche es erneut."
            }
            isWorking = false
        }
    }

    private func signIn(identityToken: Data, authorizationCode: Data) {
        isWorking = true
        errorMessage = nil
        Task {
            do {
                let reporter = try await service.signIn(identityToken: identityToken, authorizationCode: authorizationCode)
                state = .signedIn(reporter)
                isSheetPresented = false
            } catch {
                errorMessage = "Die Anmeldung ist fehlgeschlagen. Bitte versuche es erneut."
            }
            isWorking = false
        }
    }
}
