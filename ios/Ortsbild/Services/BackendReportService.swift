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

    func answer(_ option: String, reportID: String?) -> AsyncStream<ChatContent> {
        AsyncStream { continuation in
            let task = Task {
                await runAnswer(option, reportID: reportID) { continuation.yield($0) }
                continuation.finish()
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    func describe(_ text: String, reportID: String) -> AsyncStream<ChatContent> {
        AsyncStream { continuation in
            let task = Task {
                await runDescribe(text, reportID: reportID) { continuation.yield($0) }
                continuation.finish()
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    func perform(_ action: DraftAction, reportID: String?) -> AsyncStream<ChatContent> {
        switch action {
        case .approve:
            // The release is stored on the server: the report is now visible in the dashboard. Nothing is sent to an authority,
            // the dashboard replaces the single letters.
            // TODO: A weekly update email to the authorities as a reminder (decided 2026-11-10), and an own login for them.
            guard let reportID else {
                return immediately([.text(Self.noReportToRelease)])
            }
            return AsyncStream { continuation in
                let task = Task {
                    let result: Result<ReportResponse, Error>
                    do { result = .success(try await client.approve(reportID: reportID)) } catch { result = .failure(error) }
                    Self.releaseContents(for: result).forEach { continuation.yield($0) }
                    continuation.finish()
                }
                continuation.onTermination = { _ in task.cancel() }
            }
        case .revise:
            // TODO: Revise (the user's addition) is the one function of the three that is not built yet.
            return immediately([.text("Das folgt in einer späteren Version.")])
        case .delete:
            return immediately([])  // the deletion has a result the chat needs, see `deleteReport`, the view model does not come here
        }
    }

    func deleteReport(reportID: String?) async -> ReportDeletion {
        guard let reportID else { return .failed(message: Self.noReportForDeletion) }
        let result: Result<Void, Error>
        do { result = .success(try await client.deleteReport(reportID: reportID)) } catch { result = .failure(error) }
        return Self.reportDeletion(for: result)
    }

    static let noReportForDeletion = "Diese Meldung stammt aus einer älteren Version der App. Ich kann sie deshalb nicht auf dem Server löschen."

    /// What the answer of the server means. 404 counts as gone: the server does not have the report, which is what the user wanted.
    static func reportDeletion(for result: Result<Void, Error>) -> ReportDeletion {
        switch result {
        case .success:
            return .deleted
        case .failure(BackendError.server(status: 404)):
            return .deleted
        case .failure(let error):
            return .failed(message: deletionErrorText(error))
        }
    }

    static func deletionErrorText(_ error: Error) -> String {
        switch error {
        case BackendError.notSignedIn:
            return "Deine Anmeldung ist abgelaufen. Die Meldung ist noch nicht gelöscht. Bitte melde dich erneut an."
        case BackendError.server(status: 503):
            return "Die Meldung konnte nicht vollständig gelöscht werden. Sie ist noch da. Bitte versuche es später noch einmal."
        case let error as URLError where [.notConnectedToInternet, .networkConnectionLost, .timedOut, .cannotConnectToHost].contains(error.code):
            return "Keine Verbindung zum Server. Die Meldung ist noch nicht gelöscht. Bitte versuche es noch einmal."
        default:
            return "Die Meldung konnte nicht gelöscht werden. Sie ist noch da. Bitte versuche es noch einmal."
        }
    }

    func removePhoto(reportID: String?) async -> PhotoRemoval {
        guard let reportID else { return .failed(message: Self.noReportForPhoto) }
        let result: Result<ReportResponse, Error>
        do { result = .success(try await client.deletePhoto(reportID: reportID)) } catch { result = .failure(error) }
        return Self.photoRemoval(for: result)
    }

    static let noReportForPhoto = "Diese Meldung stammt aus einer älteren Version der App. Ich kann das Foto deshalb nicht auf dem Server löschen."

    /// What the answer of the server means for the photo. Only an answer without a photo counts as deleted: an older server
    /// that does not know the call would answer 404 or 405, and one that answers 200 with the photo still there did nothing.
    static func photoRemoval(for result: Result<ReportResponse, Error>) -> PhotoRemoval {
        switch result {
        case .success(let response):
            guard response.photoUrls.isEmpty else {
                return .failed(message: "Der Server hat das Foto nicht gelöscht. Es ist noch da. Bitte versuche es noch einmal.")
            }
            return .removed(draftBody: response.draft?.body)
        case .failure(let error):
            return .failed(message: photoErrorText(error))
        }
    }

    static func photoErrorText(_ error: Error) -> String {
        switch error {
        case BackendError.notSignedIn:
            return "Deine Anmeldung ist abgelaufen. Das Foto ist noch nicht gelöscht. Bitte melde dich erneut an."
        case BackendError.server(status: 404):
            return "Der Server kennt diese Meldung nicht (mehr). Ich kann das Foto dort nicht löschen."
        case let error as URLError where [.notConnectedToInternet, .networkConnectionLost, .timedOut, .cannotConnectToHost].contains(error.code):
            return "Keine Verbindung zum Server. Das Foto ist noch nicht gelöscht. Bitte versuche es noch einmal."
        default:
            return "Das Foto konnte nicht gelöscht werden. Es ist noch da. Bitte versuche es noch einmal."
        }
    }

    static let noReportToRelease = "Diese Meldung stammt aus einer älteren Version der App und kann nicht freigegeben werden. Bitte melde den Mangel noch einmal."

    /// What the chat shows after the user tapped "Freigeben". On success the status line, the sentence and the button for the
    /// dashboard. On failure an honest sentence: the report is not released, and the draft stays so the user can try again.
    static func releaseContents(for result: Result<ReportResponse, Error>) -> [ChatContent] {
        switch result {
        case .success(let response):
            var sentence = "Deine Meldung ist jetzt im Dashboard sichtbar."
            if let votes = response.caseInfo?.votes, votes > 1 {
                sentence += " Sie zählt als Stimme \(votes) für dieses Problem."
            }
            // An older server answers 200 without `approved`: then nothing was stored, do not claim it
            if response.approved == false {
                return [.text("Der Server hat die Freigabe nicht gespeichert. Bitte versuche es erneut.")]
            }
            return [.status("Meldung freigegeben"), .text(sentence), .dashboardLink(caseID: response.caseInfo?.caseId)]
        case .failure(let error):
            return [.text(releaseErrorText(error))]
        }
    }

    static func releaseErrorText(_ error: Error) -> String {
        switch error {
        case BackendError.notSignedIn:
            return "Deine Anmeldung ist abgelaufen. Bitte melde dich erneut an und gib die Meldung dann frei."
        case BackendError.server(status: 409):
            return "Diese Meldung kann noch nicht freigegeben werden, weil sie noch nicht eingeordnet ist. Bitte warte einen Moment und versuche es erneut."
        case BackendError.server(status: 404):
            return "Der Server kennt diese Meldung nicht (mehr). Bitte melde den Mangel noch einmal."
        case let error as URLError where [.notConnectedToInternet, .networkConnectionLost, .timedOut, .cannotConnectToHost].contains(error.code):
            return "Keine Verbindung zum Server. Die Meldung ist noch nicht freigegeben. Bitte versuche es noch einmal."
        default:
            return "Die Meldung konnte nicht freigegeben werden. Sie ist noch nicht im Dashboard. Bitte versuche es noch einmal."
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

    /// The answer of the user to the question what the picture shows. The server then researches and drafts.
    private func runAnswer(_ option: String, reportID: String?, emit: (ChatContent) -> Void) async {
        guard let reportID else {
            emit(.text("Diese Antwort wird noch nicht ausgewertet."))
            return
        }
        guard let category = DefectCategory(title: option) else {
            // "Keins davon": nothing to report, the report stays open on the server
            // TODO: Close the report on the server too, today it stays "waiting for an answer"
            emit(.text("Alles klar, dann kann ich hier nichts melden. Für ein anderes Problem startest du eine neue Meldung."))
            return
        }
        emit(.activity("Zuständige Stelle wird gesucht und der Entwurf geschrieben"))
        do {
            let response = try await client.answer(reportID: reportID, category: category.rawValue)
            let image = await cleanPhoto(of: response)
            await continueAfterSanitized(response, image: image, afterAnswer: true, chosenByUser: true, emit: emit)
        } catch {
            emit(.text(answerErrorText(error)))
        }
    }

    /// The user describes the problem in words. The server checks the words for personal data first, then it classifies again.
    private func runDescribe(_ text: String, reportID: String, emit: (ChatContent) -> Void) async {
        emit(.activity("Deine Beschreibung wird geprüft und eingeordnet"))
        do {
            let response = try await client.answer(reportID: reportID, text: text)
            let image = await cleanPhoto(of: response)
            await continueAfterSanitized(response, image: image, afterAnswer: true, chosenByUser: false, emit: emit)
        } catch {
            emit(.text(answerErrorText(error)))
        }
    }

    private func answerErrorText(_ error: Error) -> String {
        switch error {
        case BackendError.notSignedIn:
            "Deine Anmeldung ist abgelaufen. Bitte melde dich erneut an."
        case BackendError.server(status: 409):
            "Zu dieser Meldung kann ich keine Antwort mehr annehmen. Starte bitte eine neue Meldung, am besten mit einem klareren Foto."
        case BackendError.server(status: 503):
            "Deine Beschreibung konnte nicht geprüft werden, deshalb habe ich sie nicht verwendet. Bitte versuche es später noch einmal."
        case BackendError.server(status: 422):
            "Die Beschreibung ist zu lang oder leer. Bitte fasse dich in ein bis zwei Sätzen."
        default:
            "Die Antwort konnte nicht gesendet werden. Bitte prüfe deine Verbindung und versuche es erneut."
        }
    }

    private func cleanPhoto(of response: ReportResponse) async -> UIImage? {
        guard let path = response.photoUrls.first, let data = try? await client.photo(path: path) else { return nil }
        return UIImage(data: data)
    }

    private func present(_ response: ReportResponse, emit: (ChatContent) -> Void) async {
        switch response.status {
        case "sanitized":
            guard let report = response.report else {
                emit(.text("Die Antwort des Servers war unvollständig. Bitte versuche es erneut."))
                return
            }
            let image = await cleanPhoto(of: response)
            emit(.sanitized(SanitizedResult(text: report.text, photo: image, entries: report.redactionLog.entries)))
            await continueAfterSanitized(response, image: image, afterAnswer: false, chosenByUser: false, emit: emit)
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

    /// What follows the cleaned report: the question if the picture is not clear, otherwise category, authority and draft.
    /// `chosenByUser` is true after the user answered a question, then the category is their word and not a guess.
    private func continueAfterSanitized(
        _ response: ReportResponse, image: UIImage?, afterAnswer: Bool, chosenByUser: Bool, emit: (ChatContent) -> Void
    ) async {
        if let clarification = response.clarification {
            // Nothing is researched on a guess: ask, and wait for the answer (typed in the input field, or a button)
            let titles = clarification.options.compactMap { DefectCategory(rawValue: $0)?.title }
            let text: String
            if afterAnswer {
                text = "Damit kann ich es noch nicht einordnen. Beschreibe das Problem bitte etwas genauer oder wähle eine Kategorie."
            } else if clarification.reason == "no_defect" {
                text = "Ich erkenne hier keinen Mangel im öffentlichen Raum. Was möchtest du melden? Tippe es kurz ein oder wähle eine Kategorie."
            } else {
                text = "Ich bin mir nicht sicher, was auf dem Bild das Problem ist. Beschreibe es kurz oder wähle eine Kategorie."
            }
            emit(.clarification(reportID: response.id, text: text, options: titles + [Self.noneOfThese]))
            return
        }
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
        if chosenByUser {
            emit(.status("Kategorie: \(classification.categoryName) (von dir gewählt), \(classification.laneName)"))
        } else {
            let sure = classification.isUnsure ? ", unsicher" : ""
            emit(.status("Kategorie: \(classification.categoryName) (\(Int((classification.confidence * 100).rounded())) %\(sure)), \(classification.laneName)"))
        }
        // The same defect was reported before: this report is one more vote, the user should see that it was not lost
        if let message = response.caseInfo?.message { emit(.text(message)) }
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
                photo: image,
                reportID: response.id,
                caseID: response.caseInfo?.caseId
            )))
            emit(.text("Prüfe den Entwurf. Stimmen Stelle und Text, gib ihn frei, dann erscheint die Meldung im Dashboard."))
        } else {
            emit(.text("Ich konnte keinen Entwurf schreiben. Bitte versuche es später noch einmal."))
        }
    }

    /// The button for "none of these", handled in the app: there is nothing to report.
    static let noneOfThese = "Keins davon"
}
