//
//  BackendReportService.swift
//  Ortsbild
//

import CoreLocation
import UIKit

/// Sends a report to the backend and shows what the privacy layer made of it.
///
/// The server removes everything personal (faces, names, numbers, photo metadata) before anything
/// else happens with the report, and this is what the chat shows as proof.
struct BackendReportService: ReportService {
    let client: BackendClient
    private let location = LocationService()
    private let places = PlaceService()

    init(client: BackendClient) {
        self.client = client
    }

    func respond(photo: UIImage?, text: String?) -> AsyncStream<ChatContent> {
        AsyncStream { continuation in
            let task = Task {
                await run(photo: photo, text: text) { continuation.yield($0) }
                continuation.finish()
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    func answer(_ option: String) -> AsyncStream<ChatContent> {
        // TODO: The backend asks no follow-up questions yet (docs/classification-plan.md, C7)
        immediately([.text("Diese Antwort wird noch nicht ausgewertet.")])
    }

    func perform(_ action: DraftAction) -> AsyncStream<ChatContent> {
        switch action {
        case .approve:
            // TODO: The sending is simulated (docs/plan.md 5.7). The user sends the letter with "Teilen" under the draft.
            return immediately([
                .status("Entwurf freigegeben"),
                .text("Im Prototyp wird nichts automatisch gesendet. Mit „Teilen“ unter dem Entwurf kannst du die Nachricht samt Foto selbst an die Stelle schicken."),
            ])
        case .close:
            return immediately([.text("Die Meldung wurde geschlossen.")])
        case .revise, .wrongAuthority:
            // TODO: Revise (the user's addition) and a new research without the refused authority (docs/research-plan.md)
            return immediately([.text("Das folgt in einer späteren Version.")])
        }
    }

    /// The contents at once, one after another, without a pause.
    private func immediately(_ contents: [ChatContent]) -> AsyncStream<ChatContent> {
        AsyncStream { continuation in
            contents.forEach { continuation.yield($0) }
            continuation.finish()
        }
    }

    // MARK: Steps

    private func run(photo: UIImage?, text: String?, emit: (ChatContent) -> Void) async {
        if EmergencyCheck.matches(text) {
            emit(.emergency)
            return
        }

        emit(.activity("Standort wird bestimmt"))
        let position: CLLocation
        do {
            position = try await location.currentLocation()
        } catch LocationError.denied {
            emit(.text("Ohne Standort kann ich keine Meldung aufnehmen. Bitte erlaube den Zugriff in den Einstellungen unter Datenschutz & Sicherheit > Ortungsdienste."))
            return
        } catch {
            emit(.text("Ich konnte deinen Standort nicht bestimmen. Bitte versuche es noch einmal, am besten draußen."))
            return
        }

        // The address of the position, from the phone. Without it the report still works, only no authority is researched.
        emit(.activity("Adresse wird ermittelt"))
        let place = await places.place(for: position)
        if let place { emit(.status("Ort erkannt: \(place.line)")) }

        var jpeg: Data?
        if let photo {
            guard let data = photo.jpegForUpload() else {
                emit(.text("Das Foto konnte nicht verarbeitet werden. Bitte wähle ein anderes."))
                return
            }
            jpeg = data
        }

        // One request: the server anonymizes, classifies and searches the authority. The app cannot see the single steps.
        // TODO: Show the single steps once the answer comes by polling (docs/classification-plan.md, C8)
        emit(.activity("Daten werden anonymisiert, eingeordnet und die zuständige Stelle wird gesucht"))
        // One id per report: if the answer gets lost and we send again, the server does not create a second report
        let clientReportID = UUID().uuidString
        do {
            let response = try await sendWithOneRetry(clientReportID: clientReportID, position: position, place: place, text: text, jpeg: jpeg)
            await present(response, emit: emit)
        } catch BackendError.notSignedIn {
            emit(.text("Deine Anmeldung ist abgelaufen. Bitte melde dich erneut an."))
        } catch BackendError.server(status: 429) {
            emit(.text("Du hast in der letzten Stunde sehr viele Meldungen gesendet. Bitte versuche es später noch einmal."))
        } catch {
            emit(.text("Die Meldung konnte nicht gesendet werden. Bitte prüfe deine Verbindung und versuche es erneut."))
        }
    }

    private func sendWithOneRetry(clientReportID: String, position: CLLocation, place: Place?, text: String?, jpeg: Data?) async throws -> ReportResponse {
        func send() async throws -> ReportResponse {
            try await client.sendReport(
                clientReportID: clientReportID,
                latitude: position.coordinate.latitude,
                longitude: position.coordinate.longitude,
                accuracy: position.horizontalAccuracy,
                place: place,
                text: text,
                jpeg: jpeg
            )
        }
        let transient: Set<URLError.Code> = [.timedOut, .networkConnectionLost, .notConnectedToInternet, .cannotConnectToHost]
        do {
            return try await send()
        } catch let error as URLError where transient.contains(error.code) {
            try await Task.sleep(for: .seconds(2))
            return try await send()
        }
    }

    /// The suggested authority with its contact and the sources, or the honest note that none was found.
    private func authorityText(_ research: ResearchDTO?) -> String {
        guard let research else {
            // TODO: Let the user enter the recipient by hand, the draft step will need it
            return "Ich konnte keine zuständige Stelle finden. Das Eintragen von Hand folgt in einer späteren Version."
        }
        var lines = ["Zuständige Stelle (Vorschlag, bitte prüfen):", research.authority]
        if let channel = research.channel { lines.append("\(channel.kindName): \(channel.target)") }
        // Where the answer comes from, so the user can check it
        lines.append(contentsOf: research.sources.prefix(2).map { "Quelle: \($0)" })
        return lines.joined(separator: "\n")
    }

    private func present(_ response: ReportResponse, emit: (ChatContent) -> Void) async {
        switch response.status {
        case "sanitized":
            guard let report = response.report else {
                emit(.text("Die Antwort des Servers war unvollständig. Bitte versuche es erneut."))
                return
            }
            var image: UIImage?
            if let path = response.photoUrls.first, let data = try? await client.photo(path: path) {
                image = UIImage(data: data)
            }
            emit(.sanitized(SanitizedResult(text: report.text, photo: image, entries: report.redactionLog.entries)))
            guard let classification = response.classification else {
                emit(.status("Die Kategorie konnte noch nicht bestimmt werden"))
                emit(.text("Ohne Kategorie kann ich noch keinen Entwurf schreiben. Bitte versuche es später noch einmal."))
                return
            }
            if classification.emergency {
                // Only the hint, no ticket: in an emergency the police or the fire service must be called, not the city
                emit(.emergency)
                return
            }
            let sure = classification.isUnsure ? ", unsicher" : ""
            emit(.status("Kategorie: \(classification.categoryName) (\(Int((classification.confidence * 100).rounded())) %\(sure)), \(classification.laneName)"))
            emit(.text(authorityText(response.research)))
            if let draft = response.draft {
                emit(.draft(ReportDraft(
                    subject: draft.subject,
                    body: draft.body,
                    authority: draft.authority ?? "Empfänger noch offen",
                    version: draft.version,
                    recipient: draft.contact.map { "\($0.kindName): \($0.target)" },
                    language: draft.language,
                    summaryDE: draft.summaryDe,
                    photo: image
                )))
                emit(.text("Prüfe den Entwurf. Stimmen Stelle und Text, gib ihn frei."))
            } else {
                emit(.text("Ich konnte keinen Entwurf schreiben. Bitte versuche es später noch einmal."))
            }
        case "rejected":
            if response.reason == "too_many_faces" {
                emit(.text("Auf dem Foto sind zu viele Personen zu sehen. Ich habe es nicht gespeichert. Bitte mach ein neues Foto von nahem, ohne Personen im Bild."))
            } else {
                emit(.text("Das Foto ist nicht geeignet. Ich habe es nicht gespeichert. Bitte mach ein neues."))
            }
        case "blocked":
            emit(.text("Deine Meldung konnte aus Datenschutzgründen nicht verarbeitet werden und wurde angehalten."))
        default:
            emit(.text("Deine Meldung wird noch verarbeitet."))
        }
    }
}
