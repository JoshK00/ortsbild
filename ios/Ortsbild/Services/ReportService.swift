//
//  ReportService.swift
//  Ortsbild
//

import UIKit

/// Interface to the backend. The app runs against `MockReportService` first.
protocol ReportService {
    /// New user input (photo and/or text). The agent's replies arrive one after another.
    func respond(photo: UIImage?, text: String?) -> AsyncStream<ChatContent>
    /// The user's answer to a follow-up question (level 2).
    func answer(_ option: String) -> AsyncStream<ChatContent>
    /// Action on a draft.
    func perform(_ action: DraftAction) -> AsyncStream<ChatContent>
}
