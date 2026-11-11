//
//  MockReportService.swift
//  Ortsbild
//

import UIKit

/// Scripted responses that make the flow from docs/documentation.md visible.
struct MockReportService: ReportService {

    func respond(photo: UIImage?, text: String?) -> AsyncStream<ChatContent> {
        if EmergencyCheck.matches(text) {
            return stream([(.emergency, 0.6)])
        }

        guard photo != nil else {
            return stream([(.text("Schick mir ein Foto des Mangels, dann kümmere ich mich um den Rest."), 0.6)])
        }

        // TODO: Category and confidence will later come from the classification, hard-coded for now
        return stream([
            (.status("Foto wird auf dem Gerät anonymisiert"), 0.8),
            (.status("Kategorie erkannt: Müll (92 %)"), 1.0),
            (.question("Handelt es sich um Sperrmüll?", options: ["Ja", "Nein"]), 0.8)
        ])
    }

    func answer(_ option: String, reportID: String?) -> AsyncStream<ChatContent> {
        // TODO: The answer will later feed into classification and draft
        stream([
            (.status("Zuständige Stelle wird recherchiert"), 0.8),
            (.status("Zuständig: Ordnungsamt Musterstadt"), 1.2),
            (.draft(Self.draft(version: 1, authority: "Ordnungsamt Musterstadt")), 0.8)
        ])
    }

    func describe(_ text: String, reportID: String) -> AsyncStream<ChatContent> {
        stream([(.text("Danke, das ist der Prototyp ohne Server."), 0.4)])
    }

    func perform(_ action: DraftAction, reportID: String?) -> AsyncStream<ChatContent> {
        // TODO: Draft versions and responsible authority will later come from the backend
        switch action {
        case .approve:
            return stream([
                (.status("Meldung freigegeben"), 0.6),
                (.text("Deine Meldung ist jetzt im Dashboard sichtbar. (Prototyp ohne Server: nichts wurde gespeichert.)"), 0.6),
                (.dashboardLink(caseID: nil), 0.2)
            ])
        case .revise:
            return stream([
                (.status("Entwurf wird überarbeitet"), 0.6),
                (.draft(Self.draft(version: 2, authority: "Ordnungsamt Musterstadt")), 1.0)
            ])
        case .delete:
            return stream([])  // the deletion has a result, see `deleteReport`
        }
    }

    func deleteReport(reportID: String?) async -> ReportDeletion {
        // The scripted prototype has no server, there is nothing to delete there
        .deleted
    }

    func removePhoto(reportID: String?) async -> PhotoRemoval {
        // The scripted prototype has no server, the photo is only taken out of the chat
        .removed(draftBody: nil)
    }

    private static func draft(version: Int, authority: String) -> ReportDraft {
        ReportDraft(
            subject: "Illegale Müllablagerung",
            body: "Am gemeldeten Standort wurde Sperrmüll im öffentlichen Raum abgelagert. "
                + "Wir bitten um Prüfung und Entfernung. Ein Foto liegt bei.",
            authority: authority,
            version: version
        )
    }

    /// Emits the contents one after another, each after the given delay (in seconds).
    private func stream(_ steps: [(ChatContent, Double)]) -> AsyncStream<ChatContent> {
        AsyncStream { continuation in
            let task = Task {
                for (content, delay) in steps {
                    try? await Task.sleep(for: .seconds(delay))
                    if Task.isCancelled { break }
                    continuation.yield(content)
                }
                continuation.finish()
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}
