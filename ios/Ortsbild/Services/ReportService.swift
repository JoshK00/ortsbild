//
//  ReportService.swift
//  Ortsbild
//

import UIKit

/// What came of the removal of a photo (see `ReportService.removePhoto`).
enum PhotoRemoval: Equatable {
    /// The photo is gone. `draftBody` is the letter as the server has it now (without the line that a photo is attached),
    /// `nil` if the server sent no draft, then the app takes the line out itself.
    case removed(draftBody: String?)
    /// The photo is still there. `message` says why, in German, for the chat.
    case failed(message: String)
}

/// What came of the deletion of a report (see `ReportService.deleteReport`).
enum ReportDeletion: Equatable {
    /// The report and its photo are gone from the server (or the server did not know the report any more).
    case deleted
    /// The report is still there. `message` says why, in German, for the chat.
    case failed(message: String)
}

/// Interface to the backend (`BackendReportService`).
protocol ReportService {
    /// New user input (photo and/or text). The agent's replies arrive one after another.
    func respond(photo: UIImage?, text: String?) -> AsyncStream<ChatContent>
    /// The user's answer to a follow-up question (level 2). `reportID` says which report was asked about.
    func answer(_ option: String, reportID: String?) -> AsyncStream<ChatContent>
    /// The user describes the problem in their own words, as the answer to the open question of a report.
    /// The server sanitizes the words first, like every text, then it classifies the report again.
    func describe(_ text: String, reportID: String) -> AsyncStream<ChatContent>
    /// Action on a draft. `reportID` is the report the draft belongs to (`nil` for old drafts).
    func perform(_ action: DraftAction, reportID: String?) -> AsyncStream<ChatContent>
    /// The user takes the photo away, because a face or a plate can still be seen. The server deletes it for good.
    /// `reportID` is `nil` for old drafts.
    func removePhoto(reportID: String?) async -> PhotoRemoval
    /// The user deletes the report: the server deletes it with its photo for good. `reportID` is `nil` for old drafts.
    func deleteReport(reportID: String?) async -> ReportDeletion
}
