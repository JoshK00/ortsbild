//
//  ClarificationTests.swift
//  OrtsbildTests
//

import Foundation
import Testing
import UIKit
@testable import Ortsbild

/// The question "what is this about?" when the picture is not clear: the codes match the backend, the question stays in the
/// history and the answer goes to the report that was asked about.
@MainActor
struct ClarificationTests {
    /// Records what the chat asks the service, answers nothing.
    final class RecordingService: ReportService {
        var answers: [(option: String, reportID: String?)] = []
        var descriptions: [(text: String, reportID: String)] = []
        var responses: [(hasPhoto: Bool, text: String?)] = []

        func respond(photo: UIImage?, text: String?) -> AsyncStream<ChatContent> {
            responses.append((photo != nil, text))
            return AsyncStream { $0.finish() }
        }

        func describe(_ text: String, reportID: String) -> AsyncStream<ChatContent> {
            descriptions.append((text, reportID))
            return AsyncStream { $0.finish() }
        }

        func answer(_ option: String, reportID: String?) -> AsyncStream<ChatContent> {
            answers.append((option, reportID))
            return AsyncStream { $0.finish() }
        }

        var performed: [(action: DraftAction, reportID: String?)] = []

        func perform(_ action: DraftAction, reportID: String?) -> AsyncStream<ChatContent> {
            performed.append((action, reportID))
            return AsyncStream { $0.finish() }
        }

        /// What `removePhoto` answers, and which reports it was asked about.
        var photoRemoval: PhotoRemoval = .removed(draftBody: nil)
        var photoRemovals: [String?] = []

        func removePhoto(reportID: String?) async -> PhotoRemoval {
            photoRemovals.append(reportID)
            return photoRemoval
        }

        /// What `deleteReport` answers, and which reports it was asked about.
        var deletion: ReportDeletion = .deleted
        var deletions: [String?] = []

        func deleteReport(reportID: String?) async -> ReportDeletion {
            deletions.append(reportID)
            return deletion
        }
    }

    private func makeStore() -> TicketStore {
        TicketStore(root: FileManager.default.temporaryDirectory.appending(path: "clarification-test-\(UUID().uuidString)"))
    }

    @Test func theCodesAreTheOnesTheBackendUses() {
        // backend/classification/models.py: CLARIFICATION_CATEGORIES, in this order
        #expect(DefectCategory.allCases.map(\.rawValue) == ["litter", "graffiti", "street_light", "playground_equipment", "pothole", "tree"])
    }

    @Test func aButtonTitleFindsItsCategoryAndEveryCategoryHasADistinctTitle() {
        for category in DefectCategory.allCases { #expect(DefectCategory(title: category.title) == category) }
        #expect(Set(DefectCategory.allCases.map(\.title)).count == DefectCategory.allCases.count)
        #expect(DefectCategory(title: BackendReportService.noneOfThese) == nil)
        #expect(DefectCategory(title: "Sonstiges") == nil)
    }

    @Test func theResponseWithAQuestionIsRead() throws {
        let json = """
        {"id":"abc","status":"sanitized","reason":null,"report":null,"photo_urls":[],"classification":{"category":"pothole","lane":"hazard","emergency":false,"confidence":0.3},
         "research":null,"draft":null,"clarification":{"reason":"unclear","options":["litter","graffiti","street_light","playground_equipment","pothole","tree"]}}
        """
        let response = try JSONDecoder().decode(ReportResponse.self, from: Data(json.utf8))
        #expect(response.clarification?.reason == "unclear" && response.clarification?.options.count == 6)
        #expect(response.classification?.isUnsure == true)
    }

    @Test func aResponseWithoutAQuestionHasNone() throws {
        let json = #"{"id":"abc","status":"sanitized","reason":null,"report":null,"photo_urls":[],"classification":null,"research":null,"draft":null,"clarification":null}"#
        #expect(try JSONDecoder().decode(ReportResponse.self, from: Data(json.utf8)).clarification == nil)
    }

    @Test func theQuestionStaysInTheHistoryWithItsReportAndTheTitleForTheList() throws {
        let store = makeStore()
        let id = UUID()
        let question = ChatMessage(sender: .agent, content: .clarification(reportID: "r-42", text: "Worum geht es?", options: ["Müll", "Graffiti", "Keins davon"]))
        store.save([ChatMessage(sender: .user, content: .text("Etwas liegt dort")), question], for: id)

        let loaded = try #require(store.loadMessages(for: id))
        guard case .clarification(let reportID, let text, let options) = loaded[1].content else { Issue.record("question lost"); return }
        #expect(reportID == "r-42" && text == "Worum geht es?" && options == ["Müll", "Graffiti", "Keins davon"])
        #expect(store.tickets[0].preview == "Worum geht es?")
    }

    @Test func theAnswerGoesToTheReportThatWasAskedAbout() {
        let store = makeStore()
        let id = UUID()
        store.save([
            ChatMessage(sender: .user, content: .text("Etwas liegt dort")),
            ChatMessage(sender: .agent, content: .clarification(reportID: "r-42", text: "Worum geht es?", options: ["Graffiti"])),
        ], for: id)
        let service = RecordingService()
        let model = ChatViewModel(ticketID: id, store: store, service: service)

        model.choose(option: "Graffiti")

        #expect(service.answers.count == 1 && service.answers[0].option == "Graffiti" && service.answers[0].reportID == "r-42")
        // The answer of the user is part of the chat
        guard case .text(let shown)? = model.messages.last?.content else { Issue.record("answer not shown"); return }
        #expect(shown == "Graffiti")
    }

    /// A chat with a question that is open, as it is after the app asked what the picture shows.
    private func openQuestion(reportID: String = "r-42") -> (ChatViewModel, RecordingService) {
        let store = makeStore()
        let id = UUID()
        store.save([
            ChatMessage(sender: .user, content: .text("Etwas liegt dort")),
            ChatMessage(sender: .agent, content: .clarification(reportID: reportID, text: "Was ist das Problem?", options: ["Müll"])),
        ], for: id)
        let service = RecordingService()
        return (ChatViewModel(ticketID: id, store: store, service: service), service)
    }

    @Test func wordsTypedWhileAQuestionIsOpenAreTheAnswerAndNotANewReport() {
        let (model, service) = openQuestion()
        #expect(model.isAnswering)
        model.inputText = "  Das Schlagloch vor der Schule  "
        model.send()

        #expect(service.descriptions.count == 1 && service.descriptions[0].text == "Das Schlagloch vor der Schule" && service.descriptions[0].reportID == "r-42")
        #expect(service.responses.isEmpty)
        guard case .text(let shown)? = model.messages.last?.content else { Issue.record("answer not shown"); return }
        #expect(shown == "Das Schlagloch vor der Schule")
        #expect(model.inputText.isEmpty)
    }

    @Test func aNewPhotoWhileAQuestionIsOpenStartsANewReport() {
        let (model, service) = openQuestion()
        model.attachedPhoto = UIGraphicsImageRenderer(size: CGSize(width: 10, height: 10)).image { _ in }
        model.inputText = "Ein besseres Foto"
        model.send()
        #expect(service.responses.count == 1 && service.responses[0].hasPhoto && service.descriptions.isEmpty)
    }

    @Test func wordsWithoutAnOpenQuestionStartANewReport() {
        let store = makeStore()
        let service = RecordingService()
        let model = ChatViewModel(ticketID: UUID(), store: store, service: service)
        #expect(!model.isAnswering)
        model.inputText = "Großes Schlagloch"
        model.send()
        #expect(service.responses.count == 1 && service.descriptions.isEmpty)
    }

    @Test func emptyWordsAreNotSentAsAnAnswer() {
        let (model, service) = openQuestion()
        model.inputText = "   "
        model.send()
        #expect(service.descriptions.isEmpty && service.responses.isEmpty && !model.canSend)
    }

    @Test func theQuestionIsNoLongerOpenOnceAnythingFollowsIt() {
        let (model, _) = openQuestion()
        model.choose(option: "Müll")
        #expect(!model.isAnswering)  // the answer of the user is now the last message
    }

    @Test func aScriptedQuestionHasNoReport() {
        let store = makeStore()
        let id = UUID()
        store.save([
            ChatMessage(sender: .user, content: .text("x")),
            ChatMessage(sender: .agent, content: .question("Sperrmüll?", options: ["Ja", "Nein"])),
        ], for: id)
        let service = RecordingService()
        ChatViewModel(ticketID: id, store: store, service: service).choose(option: "Ja")
        #expect(service.answers.count == 1 && service.answers[0].reportID == nil)
    }

    @Test func noneOfTheseEndsTheQuestionInTheAppWithoutAskingTheServer() async {
        let client = BackendClient(baseURL: URL(string: "https://example.invalid")!)  // never called in this test
        let service = BackendReportService(client: client)
        var contents: [ChatContent] = []
        for await content in service.answer(BackendReportService.noneOfThese, reportID: "r-42") { contents.append(content) }
        #expect(contents.count == 1)
        guard case .text(let text)? = contents.first else { Issue.record("no text"); return }
        #expect(text.contains("nichts melden"))
    }

    @Test func anAnswerWithoutAReportIsNotSentAnywhere() async {
        let service = BackendReportService(client: BackendClient(baseURL: URL(string: "https://example.invalid")!))
        var contents: [ChatContent] = []
        for await content in service.answer("Graffiti", reportID: nil) { contents.append(content) }
        #expect(contents.count == 1)
    }

    // MARK: - Duplicates and votes

    private func decodeCase(_ json: String) throws -> CaseDTO? {
        let body = """
        {"id": "abc", "status": "sanitized", "photo_urls": [], "case": \(json)}
        """
        return try JSONDecoder().decode(ReportResponse.self, from: Data(body.utf8)).caseInfo
    }

    @Test func theCaseOfTheBackendIsDecoded() throws {
        let info = try decodeCase(#"{"votes": 3, "is_duplicate": true, "first_reported_at": "2026-11-09T10:00:00+00:00"}"#)
        #expect(info == CaseDTO(votes: 3, isDuplicate: true))
    }

    @Test func theCaseIdForTheDashboardIsDecodedWhenThereIsOne() throws {
        let info = try decodeCase(#"{"votes": 2, "is_duplicate": true, "first_reported_at": "x", "case_id": "0123456789abcdef"}"#)
        #expect(info?.caseId == "0123456789abcdef")
        let withNull = try decodeCase(#"{"votes": 2, "is_duplicate": true, "first_reported_at": "x", "case_id": null}"#)
        #expect(withNull?.caseId == nil)
    }

    @Test func aReportWithoutACaseStillDecodes() throws {
        #expect(try decodeCase("null") == nil)
    }

    @Test func aDuplicateTellsTheUserAboutTheVote() throws {
        let info = try #require(try decodeCase(#"{"votes": 2, "is_duplicate": true, "first_reported_at": "x"}"#))
        let message = try #require(info.message)
        #expect(message == "Dieses Problem wurde hier schon gemeldet. Mit deiner Freigabe zählt deine Meldung als weitere Stimme (dann 2).")
    }

    @Test func theFirstReportOfADefectSaysNothing() throws {
        let first = try #require(try decodeCase(#"{"votes": 1, "is_duplicate": false, "first_reported_at": "x"}"#))
        #expect(first.message == nil)
        let reporterOfTheCase = try #require(try decodeCase(#"{"votes": 4, "is_duplicate": false, "first_reported_at": "x"}"#))
        #expect(reporterOfTheCase.message == nil)  // the first reporter is not told again, the votes are for the authority
    }
}
