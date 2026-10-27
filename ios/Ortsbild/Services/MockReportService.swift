//
//  MockReportService.swift
//  Ortsbild
//

import UIKit

/// Scripted responses that make the flow from docs/documentation.md visible.
struct MockReportService: ReportService {

    func respond(photo: UIImage?, text: String?) -> AsyncStream<ChatContent> {
        // TODO: Emergency detection will later run through Claude Vision, for now only a keyword search in the text
        let emergencyKeywords = ["feuer", "brand", "verletzt", "gewalt", "unfall"]
        let lowered = text?.lowercased() ?? ""
        if emergencyKeywords.contains(where: lowered.contains) {
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

    func answer(_ option: String) -> AsyncStream<ChatContent> {
        // TODO: The answer will later feed into classification and draft
        stream([
            (.status("Zuständige Stelle wird recherchiert"), 0.8),
            (.status("Zuständig: Ordnungsamt Musterstadt"), 1.2),
            (.draft(Self.draft(version: 1, authority: "Ordnungsamt Musterstadt")), 0.8)
        ])
    }

    func perform(_ action: DraftAction) -> AsyncStream<ChatContent> {
        // TODO: Draft versions and responsible authority will later come from the backend
        switch action {
        case .approve:
            return stream([
                (.status("Meldung freigegeben"), 0.6),
                (.text("Die Meldung wurde gesendet. Im Prototyp wird der Versand nur simuliert."), 1.0)
            ])
        case .revise:
            return stream([
                (.status("Entwurf wird überarbeitet"), 0.6),
                (.draft(Self.draft(version: 2, authority: "Ordnungsamt Musterstadt")), 1.0)
            ])
        case .wrongAuthority:
            return stream([
                (.status("Zuständige Stelle wird neu recherchiert"), 0.6),
                (.draft(Self.draft(version: 2, authority: "Stadtreinigung Musterstadt")), 1.5)
            ])
        case .close:
            return stream([(.text("Die Meldung wurde geschlossen."), 0.4)])
        }
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
