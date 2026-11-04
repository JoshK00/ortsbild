//
//  ShareSheet.swift
//  Ortsbild
//

import SwiftUI
import UIKit

/// The share sheet of iOS. With a text and a photo together, Mail takes the text as the letter and the photo as the attachment.
struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}
