//
//  TicketStoreTests.swift
//  OrtsbildTests
//

import Foundation
import Testing
import UIKit
@testable import Ortsbild

/// The history on the phone: what is written is read back, nothing is written for an empty chat, and deleting really deletes.
@MainActor
struct TicketStoreTests {
    /// A store in its own temporary folder, so the tests do not touch each other or the real history.
    private func makeStore() -> (TicketStore, URL) {
        let root = FileManager.default.temporaryDirectory.appending(path: "tickets-test-\(UUID().uuidString)")
        return (TicketStore(root: root), root)
    }

    private func image(_ color: UIColor = .red) -> UIImage {
        UIGraphicsImageRenderer(size: CGSize(width: 40, height: 20)).image { context in
            color.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 40, height: 20))
        }
    }

    private var greeting: ChatMessage { ChatMessage(sender: .agent, content: .text("Hallo!")) }

    @Test func aChatWithoutAnythingSentLeavesNoTrace() {
        let (store, root) = makeStore()
        store.save([greeting], for: UUID())
        #expect(store.tickets.isEmpty)
        #expect(!FileManager.default.fileExists(atPath: root.appending(path: "index.json").path))
    }

    @Test func aChatIsReadBackWithEveryKindOfMessage() throws {
        let (store, _) = makeStore()
        let id = UUID()
        let photo = ChatMessage(sender: .user, content: .photo(image(), caption: "Neben der Rutsche"))
        let result = SanitizedResult(text: "Schlagloch, <PHONE>", photo: image(.blue), changes: ["1 Gesicht verdeckt"])
        let messages = [
            greeting,
            ChatMessage(sender: .user, content: .text("Schlagloch auf dem Radweg")),
            photo,
            ChatMessage(sender: .agent, content: .status("Kategorie: Schlagloch (60 %), Gefahrenstelle")),
            ChatMessage(sender: .agent, content: .sanitized(result)),
            ChatMessage(sender: .agent, content: .question("Sperrmüll?", options: ["Ja", "Nein"])),
            ChatMessage(sender: .agent, content: .draft(ReportDraft(subject: "Betreff", body: "Text", authority: "Tiefbauamt", version: 2))),
            ChatMessage(sender: .agent, content: .emergency),
        ]
        store.save(messages, for: id)

        let loaded = try #require(store.loadMessages(for: id))
        #expect(loaded.map(\.id) == messages.map(\.id))
        #expect(loaded.map(\.sender) == messages.map(\.sender))

        guard case .photo(let loadedPhoto, let caption) = loaded[2].content else { Issue.record("photo lost"); return }
        #expect(caption == "Neben der Rutsche" && loadedPhoto.size.width > 0)
        guard case .sanitized(let loadedResult) = loaded[4].content else { Issue.record("result lost"); return }
        #expect(loadedResult.text == "Schlagloch, <PHONE>" && loadedResult.changes == ["1 Gesicht verdeckt"] && loadedResult.photo != nil)
        guard case .question(let question, let options) = loaded[5].content else { Issue.record("question lost"); return }
        #expect(question == "Sperrmüll?" && options == ["Ja", "Nein"])
        guard case .draft(let draft) = loaded[6].content else { Issue.record("draft lost"); return }
        #expect(draft.authority == "Tiefbauamt" && draft.version == 2)
        guard case .emergency = loaded[7].content else { Issue.record("emergency lost"); return }
    }

    @Test func theTicketListIsKeptAcrossRestartsAndSortedByTheLastChange() {
        let (store, root) = makeStore()
        let older = UUID(), newer = UUID()
        let t1 = Date(timeIntervalSince1970: 1_000), t2 = Date(timeIntervalSince1970: 2_000)
        store.save([greeting, ChatMessage(sender: .user, content: .text("Erstes Problem"), date: t1)], for: older)
        store.save([greeting, ChatMessage(sender: .user, content: .text("Zweites Problem"), date: t2)], for: newer)
        #expect(store.tickets.map(\.title) == ["Zweites Problem", "Erstes Problem"])

        let reopened = TicketStore(root: root)  // as after a restart of the app
        #expect(reopened.tickets.map(\.id) == [newer, older])
        #expect(reopened.loadMessages(for: older)?.count == 2)
    }

    @Test func savingAgainUpdatesTheTicketAndDoesNotAddAnotherOne() {
        let (store, _) = makeStore()
        let id = UUID()
        var messages = [greeting, ChatMessage(sender: .user, content: .text("Graffiti an der Wand"))]
        store.save(messages, for: id)
        messages.append(ChatMessage(sender: .agent, content: .status("Kategorie: Graffiti (60 %), Beeinträchtigung")))
        store.save(messages, for: id)
        #expect(store.tickets.count == 1)
        #expect(store.tickets[0].preview == "Kategorie: Graffiti (60 %), Beeinträchtigung")
    }

    @Test func theTitleIsTheFirstThingTheUserWroteOrAPhotoReport() {
        #expect(TicketText.title(from: [greeting]) == TicketText.untitled)
        #expect(TicketText.title(from: [greeting, ChatMessage(sender: .user, content: .photo(image(), caption: nil))]) == "Foto-Meldung")
        let long = String(repeating: "a", count: 200)
        #expect(TicketText.title(from: [ChatMessage(sender: .user, content: .text(long))]).count == 71)  // 70 letters and the dots
        #expect(TicketText.title(from: [ChatMessage(sender: .user, content: .text("Zeile eins\nZeile zwei"))]) == "Zeile eins")
    }

    @Test func theActivityIsNeverPartOfTheChat() throws {
        let (store, _) = makeStore()
        let id = UUID()
        store.save([ChatMessage(sender: .user, content: .text("x")), ChatMessage(sender: .agent, content: .activity("Ich arbeite"))], for: id)
        #expect(try #require(store.loadMessages(for: id)).count == 1)
    }

    @Test func deletingATicketRemovesItsFilesAndTheOthersStay() {
        let (store, root) = makeStore()
        let gone = UUID(), kept = UUID()
        store.save([ChatMessage(sender: .user, content: .photo(image(), caption: "weg"))], for: gone)
        store.save([ChatMessage(sender: .user, content: .text("bleibt"))], for: kept)
        store.delete(gone)
        #expect(store.tickets.map(\.id) == [kept])
        #expect(!FileManager.default.fileExists(atPath: root.appending(path: gone.uuidString).path))
        #expect(store.loadMessages(for: kept) != nil)
    }

    @Test func deletingEverythingLeavesNothingBehind() {
        let (store, root) = makeStore()
        let ids = [UUID(), UUID()]
        for id in ids { store.save([ChatMessage(sender: .user, content: .photo(image(), caption: "x"))], for: id) }
        store.deleteAll()
        #expect(store.tickets.isEmpty)
        for id in ids { #expect(!FileManager.default.fileExists(atPath: root.appending(path: id.uuidString).path)) }
        #expect(TicketStore(root: root).tickets.isEmpty)
    }

    @Test func aMissingOrBrokenFileGivesNoCrash() throws {
        let (store, root) = makeStore()
        let id = UUID()
        store.save([ChatMessage(sender: .user, content: .text("x"))], for: id)
        try Data("not json".utf8).write(to: root.appending(path: id.uuidString).appending(path: "messages.json"))
        #expect(store.loadMessages(for: id) == nil)
        #expect(store.loadMessages(for: UUID()) == nil)
        try Data("broken".utf8).write(to: root.appending(path: "index.json"))
        #expect(TicketStore(root: root).tickets.isEmpty)
    }

    @Test func theHistoryIsLeftOutOfTheBackup() throws {
        let (_, root) = makeStore()
        let values = try root.resourceValues(forKeys: [.isExcludedFromBackupKey])
        #expect(values.isExcludedFromBackup == true)
    }
}
