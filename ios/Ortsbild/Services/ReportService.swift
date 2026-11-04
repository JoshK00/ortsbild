//
//  ReportService.swift
//  Ortsbild
//

import UIKit

/// Interface to the backend. `MockReportService` is the scripted stand-in for previews and for the steps the backend does not have yet.
protocol ReportService {
    /// New user input (photo and/or text). The agent's replies arrive one after another.
    func respond(photo: UIImage?, text: String?) -> AsyncStream<ChatContent>
    /// The user's answer to a follow-up question (level 2). `reportID` says which report was asked about, `nil` for the scripted mock.
    func answer(_ option: String, reportID: String?) -> AsyncStream<ChatContent>
    /// Action on a draft.
    func perform(_ action: DraftAction) -> AsyncStream<ChatContent>
}
