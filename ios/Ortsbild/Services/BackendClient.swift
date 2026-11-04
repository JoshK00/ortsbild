//
//  BackendClient.swift
//  Ortsbild
//

import Foundation

nonisolated enum BackendError: Error {
    /// No session, or the refresh token was refused: the user has to sign in again.
    case notSignedIn
    case server(status: Int)
    case invalidResponse
}

/// Talks to the backend. Adds the access token to every call and renews it when it is
/// about to expire or the server says 401.
///
/// An actor, so the token is renewed by one call at a time: every refresh token works only once,
/// two parallel refreshes would make the server think the token was stolen and end the session.
actor BackendClient {
    private let baseURL: URL
    private let urlSession: URLSession
    private let store: SessionStore
    private var refreshTask: Task<Session, Error>?

    init(baseURL: URL, store: SessionStore = SessionStore()) {
        self.baseURL = baseURL
        self.store = store
        let configuration = URLSessionConfiguration.default
        // The server computes on the photo (faces, text), that takes a while on the small machine.
        configuration.timeoutIntervalForRequest = 120
        self.urlSession = URLSession(configuration: configuration)
    }

    // MARK: Session

    func currentSession() -> Session? {
        store.load()
    }

    func signIn(identityToken: String, nonce: String) async throws -> Session {
        let body = try JSONEncoder().encode(["identity_token": identityToken, "nonce": nonce])
        let (data, response) = try await send(path: "/v1/auth/apple", method: "POST", body: body, contentType: "application/json")
        guard response.statusCode == 200 else { throw BackendError.server(status: response.statusCode) }
        let session = try Self.decodeSession(data)
        store.save(session)
        return session
    }

    func signOut() async {
        if let session = store.load() {
            // Best effort: if the server is not reachable the session is still removed on this phone.
            let body = try? JSONEncoder().encode(["refresh_token": session.refreshToken])
            _ = try? await send(path: "/v1/auth/logout", method: "POST", body: body, contentType: "application/json")
        }
        store.clear()
    }

    func deleteAccount() async throws {
        let (_, response) = try await authorized(path: "/v1/account", method: "DELETE")
        guard response.statusCode == 204 else { throw BackendError.server(status: response.statusCode) }
        store.clear()
    }

    // MARK: Reports

    /// Sends a report. The same `clientReportID` can be sent again after a lost answer, the server
    /// then returns the first result and creates no second report.
    func sendReport(clientReportID: String, latitude: Double, longitude: Double, accuracy: Double?, place: Place?, text: String?, jpeg: Data?) async throws -> ReportResponse {
        var form = MultipartForm()
        form.addField("client_report_id", clientReportID)
        form.addField("lat", String(latitude))
        form.addField("lon", String(longitude))
        if let accuracy, accuracy >= 0 { form.addField("accuracy_m", String(accuracy)) }
        if let place {
            // The user may have corrected these, the backend treats them as untrusted text and limits their length
            let parts = [
                ("country_code", place.countryCode), ("state", place.state), ("municipality", place.municipality),
                ("district", place.district), ("postal_code", place.postalCode), ("street", place.street),
                ("house_number", place.houseNumber),
            ]
            for (name, value) in parts {
                if let value, !value.isEmpty { form.addField(name, String(value.prefix(120))) }
            }
        }
        if let text { form.addField("text", text) }
        if let jpeg { form.addFile("photo", filename: "photo.jpg", mimeType: "image/jpeg", data: jpeg) }

        let (data, response) = try await authorized(path: "/v1/reports", method: "POST", body: form.body, contentType: form.contentType)
        guard response.statusCode == 200 else { throw BackendError.server(status: response.statusCode) }
        return try JSONDecoder().decode(ReportResponse.self, from: data)
    }

    /// The user's answer to the question what the picture shows. The server then researches the authority and writes the draft.
    func answer(reportID: String, category: String) async throws -> ReportResponse {
        let body = try JSONEncoder().encode(["category": category])
        let (data, response) = try await authorized(path: "/v1/reports/\(reportID)/answer", method: "POST", body: body, contentType: "application/json")
        guard response.statusCode == 200 else { throw BackendError.server(status: response.statusCode) }
        return try JSONDecoder().decode(ReportResponse.self, from: data)
    }

    /// The sanitized photo. `path` is what the server returned in `photo_urls`.
    func photo(path: String) async throws -> Data {
        let (data, response) = try await authorized(path: path, method: "GET")
        guard response.statusCode == 200 else { throw BackendError.server(status: response.statusCode) }
        return data
    }

    // MARK: Requests

    private func authorized(path: String, method: String, body: Data? = nil, contentType: String? = nil) async throws -> (Data, HTTPURLResponse) {
        guard var session = store.load() else { throw BackendError.notSignedIn }
        if session.expiresAt.timeIntervalSinceNow < 30 {
            session = try await refreshedSession(replacing: session)
        }
        var result = try await send(path: path, method: method, body: body, contentType: contentType, token: session.accessToken)
        if result.1.statusCode == 401 {
            session = try await refreshedSession(replacing: session)
            result = try await send(path: path, method: method, body: body, contentType: contentType, token: session.accessToken)
        }
        return result
    }

    private func refreshedSession(replacing old: Session) async throws -> Session {
        if let refreshTask { return try await refreshTask.value }
        // Somebody else may have renewed it while this call waited
        if let current = store.load(), current.refreshToken != old.refreshToken { return current }

        let task = Task { () throws -> Session in
            let body = try JSONEncoder().encode(["refresh_token": old.refreshToken])
            let (data, response) = try await send(path: "/v1/auth/refresh", method: "POST", body: body, contentType: "application/json")
            if response.statusCode == 401 {
                store.clear()  // refused for good: the session is over
                await MainActor.run { NotificationCenter.default.post(name: .backendSessionEnded, object: nil) }
                throw BackendError.notSignedIn
            }
            guard response.statusCode == 200 else { throw BackendError.server(status: response.statusCode) }
            let session = try Self.decodeSession(data)
            store.save(session)
            return session
        }
        refreshTask = task
        defer { refreshTask = nil }
        return try await task.value
    }

    private func send(path: String, method: String, body: Data?, contentType: String?, token: String? = nil) async throws -> (Data, HTTPURLResponse) {
        guard let url = URL(string: path, relativeTo: baseURL) else { throw BackendError.invalidResponse }
        var request = URLRequest(url: url)
        request.httpMethod = method
        if let contentType { request.setValue(contentType, forHTTPHeaderField: "Content-Type") }
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        let (data, response): (Data, URLResponse)
        if let body {
            (data, response) = try await urlSession.upload(for: request, from: body)
        } else {
            (data, response) = try await urlSession.data(for: request)
        }
        guard let http = response as? HTTPURLResponse else { throw BackendError.invalidResponse }
        return (data, http)
    }

    private static func decodeSession(_ data: Data) throws -> Session {
        struct TokenPair: Decodable {
            let accessToken: String
            let refreshToken: String
            let expiresIn: Double
            let reporterId: String
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let pair = try decoder.decode(TokenPair.self, from: data)
        return Session(
            accessToken: pair.accessToken,
            refreshToken: pair.refreshToken,
            expiresAt: Date(timeIntervalSinceNow: pair.expiresIn),
            reporterID: pair.reporterId
        )
    }
}

/// `multipart/form-data` body for the report upload.
nonisolated struct MultipartForm {
    private let boundary = "ortsbild-\(UUID().uuidString)"
    private var parts = Data()

    var contentType: String { "multipart/form-data; boundary=\(boundary)" }

    /// All parts plus the closing line.
    var body: Data { parts + Data("--\(boundary)--\r\n".utf8) }

    mutating func addField(_ name: String, _ value: String) {
        append("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n")
    }

    mutating func addFile(_ name: String, filename: String, mimeType: String, data: Data) {
        append("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"; filename=\"\(filename)\"\r\nContent-Type: \(mimeType)\r\n\r\n")
        parts.append(data)
        append("\r\n")
    }

    private mutating func append(_ string: String) {
        parts.append(Data(string.utf8))
    }
}
