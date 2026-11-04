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
    /// The steps after the privacy layer (category, follow-up question, draft) are not built on the server yet.
    // TODO: Replace with the real backend steps once classification, research and drafting exist.
    private let laterSteps = MockReportService()

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
        laterSteps.answer(option)
    }

    func perform(_ action: DraftAction) -> AsyncStream<ChatContent> {
        laterSteps.perform(action)
    }

    // MARK: Steps

    private func run(photo: UIImage?, text: String?, emit: (ChatContent) -> Void) async {
        if EmergencyCheck.matches(text) {
            emit(.emergency)
            return
        }

        emit(.status("Standort wird bestimmt"))
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

        var jpeg: Data?
        if let photo {
            guard let data = photo.jpegForUpload() else {
                emit(.text("Das Foto konnte nicht verarbeitet werden. Bitte wähle ein anderes."))
                return
            }
            jpeg = data
        }

        emit(.status("Daten werden anonymisiert"))
        // One id per report: if the answer gets lost and we send again, the server does not create a second report
        let clientReportID = UUID().uuidString
        do {
            let response = try await sendWithOneRetry(clientReportID: clientReportID, position: position, text: text, jpeg: jpeg)
            await present(response, emit: emit)
        } catch BackendError.notSignedIn {
            emit(.text("Deine Anmeldung ist abgelaufen. Bitte melde dich erneut an."))
        } catch BackendError.server(status: 429) {
            emit(.text("Du hast in der letzten Stunde sehr viele Meldungen gesendet. Bitte versuche es später noch einmal."))
        } catch {
            emit(.text("Die Meldung konnte nicht gesendet werden. Bitte prüfe deine Verbindung und versuche es erneut."))
        }
    }

    private func sendWithOneRetry(clientReportID: String, position: CLLocation, text: String?, jpeg: Data?) async throws -> ReportResponse {
        func send() async throws -> ReportResponse {
            try await client.sendReport(
                clientReportID: clientReportID,
                latitude: position.coordinate.latitude,
                longitude: position.coordinate.longitude,
                accuracy: position.horizontalAccuracy,
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
                emit(.text("So sieht deine Meldung aus, nachdem alles Persönliche entfernt wurde. Der Entwurf an die Behörde folgt in einer späteren Version."))
                return
            }
            if classification.emergency {
                // Only the hint, no ticket: in an emergency the police or the fire service must be called, not the city
                emit(.emergency)
                return
            }
            let sure = classification.isUnsure ? ", unsicher" : ""
            emit(.status("Kategorie: \(classification.categoryName) (\(Int((classification.confidence * 100).rounded())) %\(sure)), \(classification.laneName)"))
            emit(.text("So sieht deine Meldung aus, nachdem alles Persönliche entfernt wurde. Der Entwurf an die Behörde folgt in einer späteren Version."))
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
