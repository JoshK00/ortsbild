//
//  PhotoRemovalTests.swift
//  OrtsbildTests
//

import Foundation
import Testing
import UIKit
@testable import Ortsbild

/// The user checks the photo with the release and can take it away: the call to the server, what the chat and the draft look like
/// afterwards, the history on the phone, and what happens when the server cannot delete.
@MainActor
struct PhotoRemovalTests {
    private let base = URL(string: "https://example.org")!
    private let letter = "Am Standort ist ein Schlagloch.\n\nStandort / Location: Hauptstraße 5 | 48.13710, 11.57540\nhttps://www.openstreetmap.org/?mlat=48.13710&mlon=11.57540\nAnhang / Attachment: Foto / photo"

    private func image() -> UIImage {
        UIGraphicsImageRenderer(size: CGSize(width: 40, height: 20)).image { context in
            UIColor.red.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 40, height: 20))
        }
    }

    private func decode(_ json: String) throws -> ReportResponse {
        try JSONDecoder().decode(ReportResponse.self, from: Data(json.utf8))
    }

    private func draftMessage(reportID: String? = "r-77", photo: Bool = true) -> ChatMessage {
        ChatMessage(sender: .agent, content: .draft(ReportDraft(
            subject: "Schlagloch", body: letter, authority: "Tiefbauamt", version: 1, photo: photo ? image() : nil, reportID: reportID, caseID: "00aa11bb22cc33dd"
        )))
    }

    private func chat(_ messages: [ChatMessage], service: ClarificationTests.RecordingService, root: URL? = nil) -> (ChatViewModel, TicketStore, UUID) {
        let store = TicketStore(root: root ?? FileManager.default.temporaryDirectory.appending(path: "photo-test-\(UUID().uuidString)"))
        let id = UUID()
        store.save(messages, for: id)
        return (ChatViewModel(ticketID: id, store: store, service: service), store, id)
    }

    /// `removePhoto` works in the background, this waits until the view model is done.
    private func finish(_ model: ChatViewModel) async {
        while model.isProcessing { await Task.yield() }
    }

    // MARK: The draft after the removal

    @Test func theLineThatAPhotoIsAttachedIsTakenOutAndTheRestStays() {
        let body = ReportDraft.removingAttachmentLine(from: letter)
        #expect(!body.contains("Anhang / Attachment"))
        #expect(body.contains("Am Standort ist ein Schlagloch.") && body.contains("Standort / Location") && body.contains("openstreetmap.org"))
        #expect(!body.hasSuffix("\n"))
    }

    @Test func aLetterWithoutThatLineIsNotChanged() {
        #expect(ReportDraft.removingAttachmentLine(from: "Nur Text") == "Nur Text")
    }

    @Test func aDraftWithoutPhotoKeepsEverythingElse() {
        guard case .draft(let draft) = draftMessage().content else { Issue.record("no draft"); return }
        let bare = draft.withoutPhoto(body: nil)
        #expect(bare.photo == nil)
        #expect(bare.reportID == "r-77" && bare.caseID == "00aa11bb22cc33dd" && bare.authority == "Tiefbauamt" && bare.subject == "Schlagloch")
        #expect(!bare.body.contains("Anhang / Attachment"))
        // The letter of the server wins when there is one
        #expect(draft.withoutPhoto(body: "Neuer Brief").body == "Neuer Brief")
    }

    // MARK: What the server answer means

    @Test func anAnswerWithoutAPhotoIsARemovalAndCarriesTheNewLetter() throws {
        let response = try decode(#"{"id":"r-77","status":"sanitized","photo_urls":[],"draft":{"subject":"S","body":"Neuer Brief","summary_de":"x","language":"de","version":1}}"#)
        #expect(BackendReportService.photoRemoval(for: .success(response)) == .removed(draftBody: "Neuer Brief"))
        let noDraft = try decode(#"{"id":"r-77","status":"sanitized","photo_urls":[]}"#)
        #expect(BackendReportService.photoRemoval(for: .success(noDraft)) == .removed(draftBody: nil))
    }

    @Test func anAnswerThatStillHasThePhotoIsNotReportedAsRemoved() throws {
        let response = try decode(#"{"id":"r-77","status":"sanitized","photo_urls":["/v1/reports/r-77/photos/p1"]}"#)
        guard case .failed(let text) = BackendReportService.photoRemoval(for: .success(response)) else { Issue.record("claimed a removal"); return }
        #expect(text.contains("nicht gelöscht"))
    }

    @Test func everyFailureSaysThePhotoIsStillThere() {
        let errors: [Error] = [BackendError.notSignedIn, BackendError.server(status: 404), BackendError.server(status: 500), URLError(.notConnectedToInternet), URLError(.timedOut)]
        var sentences = Set<String>()
        for error in errors {
            guard case .failed(let text) = BackendReportService.photoRemoval(for: .failure(error)) else { Issue.record("no failure for \(error)"); continue }
            sentences.insert(text)
        }
        #expect(sentences.count == 4)  // offline and timeout share a sentence
        #expect(BackendReportService.photoErrorText(URLError(.notConnectedToInternet)).contains("noch nicht gelöscht"))
        #expect(BackendReportService.photoErrorText(BackendError.server(status: 500)).contains("noch da"))
    }

    @Test func aDraftWithoutAReportIdCannotBeRemovedOnTheServer() async {
        let service = BackendReportService(client: BackendClient(baseURL: base))  // never called: there is no report id
        #expect(await service.removePhoto(reportID: nil) == .failed(message: BackendReportService.noReportForPhoto))
    }

    // MARK: The chat

    @Test func aRemovalTakesThePhotoOutOfTheDraftAndTheProofCardAndSaysSo() async throws {
        let service = ClarificationTests.RecordingService()
        service.photoRemoval = .removed(draftBody: "Brief ohne Anhang")
        let proof = ChatMessage(sender: .agent, content: .sanitized(SanitizedResult(text: "Text", photo: image(), changes: ["1 Gesicht verdeckt"])))
        let (model, _, _) = chat([ChatMessage(sender: .user, content: .text("Schlagloch")), proof, draftMessage()], service: service)

        model.removePhoto()
        #expect(model.isProcessing)
        await finish(model)

        #expect(service.photoRemovals == ["r-77"])
        guard case .sanitized(let result) = model.messages[1].content, case .draft(let draft) = model.messages[2].content else { Issue.record("messages lost"); return }
        #expect(result.photo == nil && result.changes == ["1 Gesicht verdeckt"])
        #expect(draft.photo == nil && draft.body == "Brief ohne Anhang" && draft.reportID == "r-77")
        guard case .text(let text)? = model.messages.last?.content else { Issue.record("no text"); return }
        #expect(text == ChatViewModel.photoRemovedText)
    }

    @Test func aRemovalWithoutALetterFromTheServerTakesTheLineOutHere() async {
        let service = ClarificationTests.RecordingService()  // answers `.removed(draftBody: nil)`
        let (model, _, _) = chat([ChatMessage(sender: .user, content: .text("x")), draftMessage()], service: service)
        model.removePhoto()
        await finish(model)
        guard case .draft(let draft) = model.messages[1].content else { Issue.record("no draft"); return }
        #expect(draft.photo == nil && !draft.body.contains("Anhang / Attachment"))
    }

    @Test func aFailedRemovalKeepsThePhotoAndTheDraftStaysOpen() async {
        let service = ClarificationTests.RecordingService()
        service.photoRemoval = .failed(message: "Keine Verbindung zum Server. Das Foto ist noch nicht gelöscht.")
        let draft = draftMessage()
        let (model, _, _) = chat([ChatMessage(sender: .user, content: .text("x")), draft], service: service)

        model.removePhoto()
        await finish(model)

        guard case .draft(let kept) = model.messages[1].content, case .text(let text)? = model.messages.last?.content else { Issue.record("messages lost"); return }
        #expect(kept.photo != nil && kept.body.contains("Anhang / Attachment"))
        #expect(text.contains("noch nicht gelöscht"))
        #expect(model.isActive(draft) && model.canRemovePhoto(draft) && !model.isProcessing)
    }

    @Test func onlyTheNewestDraftWithAPhotoCanLoseIt() {
        let older = draftMessage(reportID: "r-1"), newest = draftMessage(reportID: "r-2"), bare = draftMessage(reportID: "r-3", photo: false)
        let (model, _, _) = chat([ChatMessage(sender: .user, content: .text("x")), older, newest], service: ClarificationTests.RecordingService())
        #expect(!model.canRemovePhoto(older) && model.canRemovePhoto(newest))
        let (withoutPhoto, _, _) = chat([ChatMessage(sender: .user, content: .text("x")), bare], service: ClarificationTests.RecordingService())
        #expect(!withoutPhoto.canRemovePhoto(bare))
    }

    @Test func theRemovalStillWorksAfterTheRelease() {
        let draft = draftMessage()
        let link = ChatMessage(sender: .agent, content: .dashboardLink(caseID: nil))
        let (model, _, _) = chat([ChatMessage(sender: .user, content: .text("x")), draft, link], service: ClarificationTests.RecordingService())
        #expect(!model.isActive(draft))  // the release is done, the buttons of the draft are closed
        #expect(model.canRemovePhoto(draft))  // but the photo can still be taken out of the dashboard
    }

    @Test func aDraftThatIsRemovedTwiceAsksTheServerOnlyOnce() async {
        let service = ClarificationTests.RecordingService()
        let (model, _, _) = chat([ChatMessage(sender: .user, content: .text("x")), draftMessage()], service: service)
        model.removePhoto()
        model.removePhoto()  // while the first one runs, and again after it
        await finish(model)
        model.removePhoto()
        #expect(service.photoRemovals.count == 1)
    }

    // MARK: The history on the phone

    @Test func theHistoryHasNoPhotoAfterTheRemovalAndTheFilesAreGone() async throws {
        let root = FileManager.default.temporaryDirectory.appending(path: "photo-history-\(UUID().uuidString)")
        let proof = ChatMessage(sender: .agent, content: .sanitized(SanitizedResult(text: "Text", photo: image(), changes: [])))
        let draft = draftMessage()
        let (model, store, id) = chat([ChatMessage(sender: .user, content: .text("x")), proof, draft], service: ClarificationTests.RecordingService(), root: root)

        let folder = root.appending(path: id.uuidString)
        let draftFile = folder.appending(path: "\(draft.id.uuidString)-draft.jpg"), proofFile = folder.appending(path: "\(proof.id.uuidString)-clean.jpg")
        #expect(FileManager.default.fileExists(atPath: draftFile.path) && FileManager.default.fileExists(atPath: proofFile.path))

        model.removePhoto()
        await finish(model)

        let loaded = try #require(store.loadMessages(for: id))
        guard case .sanitized(let result) = loaded[1].content, case .draft(let reloaded) = loaded[2].content else { Issue.record("messages lost"); return }
        #expect(result.photo == nil && reloaded.photo == nil && reloaded.reportID == "r-77")
        #expect(!FileManager.default.fileExists(atPath: draftFile.path), "the photo of the draft is still on the phone")
        #expect(!FileManager.default.fileExists(atPath: proofFile.path), "the photo of the proof card is still on the phone")
    }
}

/// The calls to the server (photo removal and report deletion), with a stub instead of the network. They share the stub, so they
/// are in one serialized suite.
@Suite(.serialized)
@MainActor
struct PhotoRemovalClientTests {
    private let base = URL(string: "https://example.org")!

    /// A session store of its own, so the tests never touch the session of the app in the Keychain.
    private func store(expiresIn seconds: TimeInterval = 3600) -> SessionStore {
        let store = SessionStore(service: "com.Joshua-Kehrer.Ortsbild.tests-\(UUID().uuidString)")
        store.save(Session(accessToken: "access-1", refreshToken: "refresh-1", expiresAt: Date(timeIntervalSinceNow: seconds), reporterID: "usr-aabbccddeeff"))
        return store
    }

    private func client(_ store: SessionStore) -> BackendClient {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        return BackendClient(baseURL: base, store: store, urlSession: URLSession(configuration: configuration))
    }

    private let removed = #"{"id":"r-77","status":"sanitized","photo_urls":[]}"#

    @Test func theCallIsADeleteOfThePhotoOfTheReportWithTheToken() async throws {
        let sessions = store()
        defer { sessions.clear() }
        StubURLProtocol.reset { _ in (200, Data(removed.utf8)) }

        let response = try await client(sessions).deletePhoto(reportID: "r-77")

        #expect(response.photoUrls.isEmpty)
        let sent = StubURLProtocol.requests
        #expect(sent.count == 1 && sent[0].httpMethod == "DELETE" && sent[0].url?.path == "/v1/reports/r-77/photo")
        #expect(sent[0].value(forHTTPHeaderField: "Authorization") == "Bearer access-1")
    }

    @Test func aReportThatTheServerDoesNotKnowIsA404ForTheApp() async {
        let sessions = store()
        defer { sessions.clear() }
        StubURLProtocol.reset { _ in (404, Data(#"{"detail":"no such report"}"#.utf8)) }
        await #expect(throws: BackendError.self) { _ = try await client(sessions).deletePhoto(reportID: "nope") }
    }

    // MARK: Deleting the report

    @Test func deletingAReportIsADeleteOfTheReportWithTheTokenAndAnswers204WithoutABody() async throws {
        let sessions = store()
        defer { sessions.clear() }
        StubURLProtocol.reset { _ in (204, Data()) }

        try await client(sessions).deleteReport(reportID: "r-77")

        let sent = StubURLProtocol.requests
        #expect(sent.count == 1 && sent[0].httpMethod == "DELETE" && sent[0].url?.path == "/v1/reports/r-77")
        #expect(sent[0].value(forHTTPHeaderField: "Authorization") == "Bearer access-1")
    }

    @Test func aDeletionThatTheServerDoesNotConfirmWith204IsAnError() async {
        let sessions = store()
        defer { sessions.clear() }
        for status in [404, 503, 200] {
            StubURLProtocol.reset { _ in (status, Data()) }
            var seen: Int?
            do { try await client(sessions).deleteReport(reportID: "r-77") } catch BackendError.server(status: let code) { seen = code } catch {}
            #expect(seen == status)
        }
    }

    @Test func anExpiredAccessTokenIsRenewedOnceAndTheDeletionIsRepeated() async throws {
        let sessions = store()
        defer { sessions.clear() }
        var deletes = 0
        StubURLProtocol.reset { request in
            if request.url?.path == "/v1/auth/refresh" {
                return (200, Data(#"{"access_token":"access-2","refresh_token":"refresh-2","expires_in":3600,"reporter_id":"usr-aabbccddeeff"}"#.utf8))
            }
            deletes += 1
            return request.value(forHTTPHeaderField: "Authorization") == "Bearer access-2" ? (204, Data()) : (401, Data())
        }
        try await client(sessions).deleteReport(reportID: "r-77")
        #expect(deletes == 2 && sessions.load()?.accessToken == "access-2")
    }

    @Test func anExpiredAccessTokenIsRenewedOnceAndTheCallIsRepeated() async throws {
        let sessions = store()
        defer { sessions.clear() }
        var deletes = 0
        StubURLProtocol.reset { request in
            if request.url?.path == "/v1/auth/refresh" {
                return (200, Data(#"{"access_token":"access-2","refresh_token":"refresh-2","expires_in":3600,"reporter_id":"usr-aabbccddeeff"}"#.utf8))
            }
            deletes += 1
            return request.value(forHTTPHeaderField: "Authorization") == "Bearer access-2" ? (200, Data(removed.utf8)) : (401, Data())
        }

        let response = try await client(sessions).deletePhoto(reportID: "r-77")

        #expect(response.photoUrls.isEmpty && deletes == 2)
        #expect(sessions.load()?.accessToken == "access-2")
    }
}

/// Answers every request of the client without a network. The handler is set per test, the tests of the suite run one by one.
nonisolated final class StubURLProtocol: URLProtocol, @unchecked Sendable {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var handler: (@Sendable (URLRequest) -> (Int, Data))?
    nonisolated(unsafe) private static var seen: [URLRequest] = []

    static func reset(_ handler: @escaping @Sendable (URLRequest) -> (Int, Data)) {
        lock.lock(); defer { lock.unlock() }
        self.handler = handler
        seen = []
    }

    static var requests: [URLRequest] {
        lock.lock(); defer { lock.unlock() }
        return seen.filter { $0.url?.path != "/v1/auth/refresh" }
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.lock.lock()
        Self.seen.append(request)
        let handler = Self.handler
        Self.lock.unlock()
        let (status, data) = handler?(request) ?? (500, Data())
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1", headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
