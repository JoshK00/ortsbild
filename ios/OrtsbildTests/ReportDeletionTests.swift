//
//  ReportDeletionTests.swift
//  OrtsbildTests
//

import Foundation
import Testing
import UIKit
@testable import Ortsbild

/// The draft card has three actions (release, revise, delete). Deleting removes the report on the server: what the chat and the card
/// look like afterwards, the history on the phone, and what each answer of the server means. The call itself is tested with the stub
/// in `PhotoRemovalClientTests`.
@MainActor
struct ReportDeletionTests {
    private func image() -> UIImage {
        UIGraphicsImageRenderer(size: CGSize(width: 40, height: 20)).image { context in
            UIColor.red.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 40, height: 20))
        }
    }

    private func draftMessage(reportID: String? = "r-77") -> ChatMessage {
        ChatMessage(sender: .agent, content: .draft(ReportDraft(
            subject: "Schlagloch", body: "Text\nAnhang / Attachment: Foto / photo", authority: "Tiefbauamt", version: 1,
            photo: image(), reportID: reportID, caseID: "00aa11bb22cc33dd"
        )))
    }

    private func chat(_ messages: [ChatMessage], service: ClarificationTests.RecordingService, root: URL? = nil) -> (ChatViewModel, TicketStore, UUID) {
        let store = TicketStore(root: root ?? FileManager.default.temporaryDirectory.appending(path: "deletion-test-\(UUID().uuidString)"))
        let id = UUID()
        store.save(messages, for: id)
        return (ChatViewModel(ticketID: id, store: store, service: service), store, id)
    }

    private func finish(_ model: ChatViewModel) async {
        while model.isProcessing { await Task.yield() }
    }

    // MARK: The three actions

    @Test func theDraftHasExactlyTheActionsReleaseReviseAndDelete() {
        #expect(DraftAction.allCases == [.approve, .revise, .delete])
    }

    @Test func releasingAndRevisingStillGoToTheServiceAndTheUserSeesWhatTheyPressed() {
        let service = ClarificationTests.RecordingService()
        let (model, _, _) = chat([ChatMessage(sender: .user, content: .text("x")), draftMessage()], service: service)
        model.perform(.approve)
        model.perform(.revise)
        #expect(service.performed.map(\.action) == [.approve, .revise])
        #expect(service.performed.allSatisfy { $0.reportID == "r-77" })
        let userTexts = model.messages.filter { $0.sender == .user }.compactMap { message -> String? in
            if case .text(let text) = message.content { text } else { nil }
        }
        #expect(userTexts.suffix(2) == ["Freigeben", "Überarbeiten"])
    }

    @Test func theTextsOfTheCardAreGoneWhereTheTeamStruckThem() throws {
        // The card has no "Falsche Stelle", no "Schließen" and no "Teilen" any more
        let sources = try ["Ortsbild/Views/DraftCard.swift", "Ortsbild/ViewModels/ChatViewModel.swift"].map { path -> String in
            let root = URL(filePath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            return try String(contentsOf: root.appending(path: path), encoding: .utf8)
        }
        for source in sources {
            #expect(!source.contains("Falsche Stelle") && !source.contains("wrongAuthority") && !source.contains("\"Teilen\"") && !source.contains("\"Schließen\""))
        }
    }

    // MARK: Deleting

    @Test func aDeletionDeletesTheReportOnTheServerAndClosesTheCard() async throws {
        let service = ClarificationTests.RecordingService()
        let proof = ChatMessage(sender: .agent, content: .sanitized(SanitizedResult(text: "Text", photo: image(), changes: ["1 Gesicht verdeckt"])))
        let draft = draftMessage()
        let (model, _, _) = chat([ChatMessage(sender: .user, content: .text("x")), proof, draft], service: service)
        #expect(model.isActive(draft))

        model.perform(.delete)
        #expect(model.isProcessing)
        await finish(model)

        #expect(service.deletions == ["r-77"] && service.performed.isEmpty)  // the deletion has its own call
        guard let kept = model.messages.first(where: { $0.id == draft.id }), case .draft(let card) = kept.content,
              case .sanitized(let result)? = model.messages.first(where: { $0.id == proof.id })?.content
        else { Issue.record("messages lost"); return }
        #expect(card.isDeleted && card.photo == nil && card.reportID == "r-77")
        #expect(result.photo == nil && result.changes == ["1 Gesicht verdeckt"])
        #expect(!model.isActive(kept), "the buttons of a deleted draft must not work")
        #expect(!model.canRemovePhoto(kept))
        guard case .text(let text)? = model.messages.last?.content else { Issue.record("no text"); return }
        #expect(text == "Die Meldung wurde gelöscht.")
    }

    @Test func aFailedDeletionChangesNothingAndTheDraftStaysOpen() async {
        let service = ClarificationTests.RecordingService()
        service.deletion = .failed(message: "Keine Verbindung zum Server. Die Meldung ist noch nicht gelöscht.")
        let draft = draftMessage()
        let (model, _, _) = chat([ChatMessage(sender: .user, content: .text("x")), draft], service: service)

        model.perform(.delete)
        await finish(model)

        guard case .draft(let kept) = model.messages[1].content, case .text(let text)? = model.messages.last?.content else { Issue.record("messages lost"); return }
        #expect(!kept.isDeleted && kept.photo != nil)
        #expect(text.contains("noch nicht gelöscht"))
        #expect(model.isActive(draft) && !model.isProcessing)
    }

    @Test func aDeletedDraftIsNotDeletedAgain() async {
        let service = ClarificationTests.RecordingService()
        let (model, _, _) = chat([ChatMessage(sender: .user, content: .text("x")), draftMessage()], service: service)
        model.perform(.delete)
        await finish(model)
        model.perform(.delete)
        await finish(model)
        #expect(service.deletions.count == 1)
    }

    // MARK: The history on the phone

    @Test func theHistoryKeepsTheDeletedMarkAndHasNoPhotoFileAfterTheDeletion() async throws {
        let root = FileManager.default.temporaryDirectory.appending(path: "deletion-history-\(UUID().uuidString)")
        let proof = ChatMessage(sender: .agent, content: .sanitized(SanitizedResult(text: "Text", photo: image(), changes: [])))
        let draft = draftMessage()
        let (model, store, id) = chat([ChatMessage(sender: .user, content: .text("x")), proof, draft], service: ClarificationTests.RecordingService(), root: root)
        let folder = root.appending(path: id.uuidString)
        let draftFile = folder.appending(path: "\(draft.id.uuidString)-draft.jpg"), proofFile = folder.appending(path: "\(proof.id.uuidString)-clean.jpg")
        #expect(FileManager.default.fileExists(atPath: draftFile.path) && FileManager.default.fileExists(atPath: proofFile.path))

        model.perform(.delete)
        await finish(model)

        let loaded = try #require(store.loadMessages(for: id))
        guard case .draft(let reloaded) = loaded[2].content else { Issue.record("draft lost"); return }
        #expect(reloaded.isDeleted && reloaded.photo == nil)
        #expect(!FileManager.default.fileExists(atPath: draftFile.path), "the photo of the draft is still on the phone")
        #expect(!FileManager.default.fileExists(atPath: proofFile.path), "the photo of the proof card is still on the phone")
        // A card that was saved before the field existed is read as not deleted
        let reopened = ChatViewModel(ticketID: id, store: store, service: ClarificationTests.RecordingService())
        let card = try #require(reopened.messages.first { if case .draft = $0.content { true } else { false } })
        #expect(!reopened.isActive(card))
    }

    // MARK: What the answer of the server means

    @Test func successAndA404BothMeanTheReportIsGone() {
        #expect(BackendReportService.reportDeletion(for: .success(())) == .deleted)
        #expect(BackendReportService.reportDeletion(for: .failure(BackendError.server(status: 404))) == .deleted)
    }

    @Test func everyOtherAnswerKeepsTheReportAndSaysWhy() throws {
        func message(_ error: Error) throws -> String {
            guard case .failed(let text) = BackendReportService.reportDeletion(for: .failure(error)) else { throw TestError.notFailed }
            return text
        }
        #expect(try message(BackendError.server(status: 503)).contains("Sie ist noch da"))
        #expect(try message(BackendError.notSignedIn).contains("noch nicht gelöscht"))
        #expect(try message(URLError(.notConnectedToInternet)).contains("Keine Verbindung"))
        #expect(try message(BackendError.server(status: 500)).contains("Sie ist noch da"))
        #expect(try message(BackendError.invalidResponse).contains("noch da"))
    }

    @Test func aDraftFromAnOlderVersionHasNoReportIdAndSaysItCannotBeDeletedOnTheServer() async {
        let service = BackendReportService(client: BackendClient(baseURL: URL(string: "https://example.org")!))  // never called: there is no report id
        #expect(await service.deleteReport(reportID: nil) == .failed(message: BackendReportService.noReportForDeletion))
    }

    @Test func theScriptedPrototypeDeletesWithoutAServer() async {
        #expect(await MockReportService().deleteReport(reportID: nil) == .deleted)
    }

    private enum TestError: Error { case notFailed }
}
