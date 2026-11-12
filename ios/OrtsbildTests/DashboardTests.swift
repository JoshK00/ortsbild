//
//  DashboardTests.swift
//  OrtsbildTests
//

import Foundation
import Testing
@testable import Ortsbild

/// The release of a report and the dashboard tab: what the app reads from the server, which links stay in the web view,
/// and what the chat says after "Freigeben".
@MainActor
struct DashboardTests {
    private let base = URL(string: "https://example.org")!

    private func decode(_ json: String) throws -> ReportResponse {
        try JSONDecoder().decode(ReportResponse.self, from: Data(json.utf8))
    }

    // MARK: Reading the answer

    @Test func approvedIsReadWhenThere() throws {
        let released = try decode(#"{"id":"abc","status":"sanitized","photo_urls":[],"approved":true}"#)
        #expect(released.isApproved)
        let open = try decode(#"{"id":"abc","status":"sanitized","photo_urls":[],"approved":false}"#)
        #expect(!open.isApproved)
    }

    @Test func anOlderServerWithoutApprovedStillDecodesAsNotReleased() throws {
        let old = try decode(#"{"id":"abc","status":"sanitized","photo_urls":[]}"#)
        #expect(old.approved == nil && !old.isApproved && old.caseInfo == nil)
    }

    // MARK: The chat after "Freigeben"

    @Test func aReleaseTellsTheUserAndOffersTheDashboard() throws {
        let response = try decode(#"{"id":"abc","status":"sanitized","photo_urls":[],"approved":true,"case":{"votes":1,"is_duplicate":false,"case_id":"00aa11bb22cc33dd"}}"#)
        let contents = BackendReportService.releaseContents(for: .success(response))
        #expect(contents.count == 3)
        guard case .status(let status) = contents[0], case .text(let text) = contents[1], case .dashboardLink(let caseID) = contents[2] else {
            Issue.record("unexpected contents"); return
        }
        #expect(status == "Meldung freigegeben")
        #expect(text == "Deine Meldung ist jetzt im Dashboard sichtbar.")
        #expect(caseID == "00aa11bb22cc33dd")
    }

    @Test func aReleaseToAnExistingCaseSaysWhichVoteItIs() throws {
        let response = try decode(#"{"id":"abc","status":"sanitized","photo_urls":[],"approved":true,"case":{"votes":3,"is_duplicate":true,"case_id":"00aa11bb22cc33dd"}}"#)
        guard case .text(let text) = BackendReportService.releaseContents(for: .success(response))[1] else { Issue.record("no text"); return }
        #expect(text.contains("Stimme 3"))
    }

    @Test func aReleaseWithoutACaseIdStillOpensThePlainDashboard() throws {
        let response = try decode(#"{"id":"abc","status":"sanitized","photo_urls":[],"approved":true}"#)
        guard case .dashboardLink(let caseID) = BackendReportService.releaseContents(for: .success(response))[2] else { Issue.record("no link"); return }
        #expect(caseID == nil)
    }

    @Test func anAnswerThatSaysNotReleasedIsNotReportedAsReleased() throws {
        let response = try decode(#"{"id":"abc","status":"sanitized","photo_urls":[],"approved":false}"#)
        let contents = BackendReportService.releaseContents(for: .success(response))
        #expect(contents.count == 1)
        if case .dashboardLink = contents[0] { Issue.record("claimed a release that did not happen") }
    }

    @Test func everyFailureHasAnHonestSentenceAndNoDashboardLink() {
        let errors: [Error] = [
            BackendError.notSignedIn, BackendError.server(status: 409), BackendError.server(status: 404),
            BackendError.server(status: 500), URLError(.notConnectedToInternet), URLError(.timedOut),
        ]
        var sentences = Set<String>()
        for error in errors {
            let contents = BackendReportService.releaseContents(for: .failure(error))
            #expect(contents.count == 1)
            guard case .text(let text) = contents[0] else { Issue.record("no text for \(error)"); continue }
            sentences.insert(text)
        }
        // Offline and timeout share a sentence, the other four differ
        #expect(sentences.count == 5)
        #expect(BackendReportService.releaseErrorText(URLError(.notConnectedToInternet)).contains("noch nicht freigegeben"))
        #expect(BackendReportService.releaseErrorText(BackendError.server(status: 500)).contains("nicht im Dashboard"))
    }

    @Test func aDraftWithoutAReportIdCannotBeReleased() async {
        let service = BackendReportService(client: BackendClient(baseURL: base))  // never called: there is no report id
        var contents: [ChatContent] = []
        for await content in service.perform(.approve, reportID: nil) { contents.append(content) }
        #expect(contents.count == 1)
        guard case .text(let text)? = contents.first else { Issue.record("no text"); return }
        #expect(text == BackendReportService.noReportToRelease)
    }

    // MARK: The chat view model

    private func chatWith(_ messages: [ChatMessage]) -> (ChatViewModel, ClarificationTests.RecordingService) {
        let store = TicketStore(root: FileManager.default.temporaryDirectory.appending(path: "dashboard-test-\(UUID().uuidString)"))
        let id = UUID()
        store.save(messages, for: id)
        let service = ClarificationTests.RecordingService()
        return (ChatViewModel(ticketID: id, store: store, service: service), service)
    }

    private func draftMessage(reportID: String?, caseID: String? = nil) -> ChatMessage {
        ChatMessage(sender: .agent, content: .draft(ReportDraft(subject: "S", body: "B", authority: "Amt", version: 1, reportID: reportID, caseID: caseID)))
    }

    @Test func theReleaseGoesToTheReportOfTheDraft() {
        let (model, service) = chatWith([ChatMessage(sender: .user, content: .text("Schlagloch")), draftMessage(reportID: "r-77")])
        model.perform(.approve)
        #expect(service.performed.count == 1 && service.performed[0].reportID == "r-77")
    }

    @Test func theDraftStaysOpenAfterAnErrorAndClosesOnceItIsReleased() {
        let draft = draftMessage(reportID: "r-77")
        let (model, _) = chatWith([ChatMessage(sender: .user, content: .text("Schlagloch")), draft])
        #expect(model.isActive(draft))

        // An error text after the draft: the user can try again
        let failed = ChatMessage(sender: .agent, content: .text("Keine Verbindung zum Server."))
        let (retryModel, _) = chatWith([ChatMessage(sender: .user, content: .text("Schlagloch")), draft, failed])
        #expect(retryModel.isActive(draft))

        // Released: the draft is closed
        let link = ChatMessage(sender: .agent, content: .dashboardLink(caseID: nil))
        let (releasedModel, _) = chatWith([ChatMessage(sender: .user, content: .text("Schlagloch")), draft, link])
        #expect(!releasedModel.isActive(draft))
        #expect(releasedModel.isActive(link))
    }

    @Test func onlyTheNewestDraftIsOpen() {
        let first = draftMessage(reportID: "r-1"), second = draftMessage(reportID: "r-2")
        let (model, _) = chatWith([ChatMessage(sender: .user, content: .text("x")), first, second])
        #expect(!model.isActive(first) && model.isActive(second))
    }

    @Test func theDraftAndTheLinkSurviveTheHistoryOnThePhone() throws {
        let store = TicketStore(root: FileManager.default.temporaryDirectory.appending(path: "dashboard-test-\(UUID().uuidString)"))
        let id = UUID()
        store.save([
            ChatMessage(sender: .user, content: .text("x")),
            draftMessage(reportID: "r-77", caseID: "00aa11bb22cc33dd"),
            ChatMessage(sender: .agent, content: .dashboardLink(caseID: "00aa11bb22cc33dd")),
            ChatMessage(sender: .agent, content: .dashboardLink(caseID: nil)),
        ], for: id)
        let loaded = try #require(store.loadMessages(for: id))
        guard case .draft(let draft) = loaded[1].content, case .dashboardLink(let first) = loaded[2].content, case .dashboardLink(let second) = loaded[3].content else {
            Issue.record("messages lost"); return
        }
        #expect(draft.reportID == "r-77" && draft.caseID == "00aa11bb22cc33dd")
        #expect(first == "00aa11bb22cc33dd" && second == nil)
        #expect(store.tickets[0].preview == "Im Dashboard sichtbar")
    }

    // MARK: The tab and the web view

    @Test func theDashboardAddressHasTheAppFlagAndTheCase() {
        #expect(DashboardRoute.url(base: base).absoluteString == "https://example.org/dashboard/?app=1")
        #expect(DashboardRoute.url(base: base, caseID: "00aa11bb22cc33dd").absoluteString == "https://example.org/dashboard/?app=1#case=00aa11bb22cc33dd")
    }

    @Test func aCaseIdThatIsNotHexNeverReachesTheAddress() {
        for bad in ["", "../x", "abc def", "ABC", "x\"onload=1", String(repeating: "a", count: 65)] {
            #expect(DashboardRoute.url(base: base, caseID: bad).absoluteString == "https://example.org/dashboard/?app=1")
        }
    }

    @Test func onlyOurOwnHostStaysInTheWebView() {
        func decide(_ address: String) -> DashboardRoute.Navigation { DashboardRoute.navigation(for: URL(string: address)!, base: base) }
        #expect(decide("https://example.org/dashboard/?app=1#case=aa") == .allow)
        #expect(decide("https://EXAMPLE.org/v1/public/cases") == .allow)
        #expect(decide("about:blank") == .allow)
        #expect(decide("https://www.openstreetmap.org/copyright") == .external)
        #expect(decide("https://example.org.evil.test/") == .external)
        #expect(decide("http://example.org/dashboard/") == .external)  // not over https: not ours
        #expect(decide("mailto:amt@example.org") == .external)
        #expect(decide("javascript:alert(1)") == .cancel)
        #expect(decide("file:///etc/passwd") == .cancel)
        #expect(decide("about:srcdoc") == .cancel)
    }

    @Test func theDashboardIsLoadedAgainOnlyAfterAWhileAway() {
        let now = Date()
        #expect(!DashboardRoute.needsReload(leftAt: nil, now: now))
        #expect(!DashboardRoute.needsReload(leftAt: now.addingTimeInterval(-30), now: now))
        #expect(DashboardRoute.needsReload(leftAt: now.addingTimeInterval(-61), now: now))
    }

    @Test func theErrorTextsAreHonest() {
        #expect(DashboardRoute.message(for: URLError(.notConnectedToInternet)).contains("offline"))
        #expect(DashboardRoute.message(for: URLError(.timedOut)).contains("antwortet nicht"))
        #expect(DashboardRoute.message(for: URLError(.badURL)) == "Das Dashboard konnte nicht geladen werden.")
        #expect(DashboardRoute.message(forHTTPStatus: 404).contains("noch nicht verfügbar"))
        #expect(DashboardRoute.message(forHTTPStatus: 502).contains("502"))
    }

    @Test func showingTheDashboardSwitchesTheTabAndRemembersTheCase() {
        let navigation = AppNavigation()
        #expect(navigation.selectedTab == .report && navigation.dashboardCaseID == nil)
        navigation.showDashboard(caseID: "00aa11bb22cc33dd")
        #expect(navigation.selectedTab == .dashboard && navigation.dashboardCaseID == "00aa11bb22cc33dd")
        navigation.selectedTab = .report
        navigation.showDashboard()
        #expect(navigation.selectedTab == .dashboard && navigation.dashboardCaseID == nil)
    }
}
