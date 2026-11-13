//
//  QuickReplyBar.swift
//  Ortsbild
//

import SwiftUI

/// Tap replies for a follow-up question (level 2). The replies sit next to each other and move to the next line when the
/// row is full, a word is never broken into letters.
struct QuickReplyBar: View {
    let options: [String]
    let isEnabled: Bool
    let onSelect: (String) -> Void

    var body: some View {
        FlowLayout(spacing: 8) {
            ForEach(options, id: \.self) { option in
                Button(option) { onSelect(option) }
                    .buttonStyle(GlassButtonStyle())
                    .lineLimit(1)
                    .disabled(!isEnabled)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Places its children in a row and starts a new row when the next child does not fit into the width any more.
/// Every child gets the size it wants (its ideal size), so a pill is as wide as its text.
private struct FlowLayout: Layout {
    var spacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        arrange(subviews, maxWidth: proposal.width ?? .infinity).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let origins = arrange(subviews, maxWidth: bounds.width).origins
        for (index, origin) in origins.enumerated() {
            subviews[index].place(at: CGPoint(x: bounds.minX + origin.x, y: bounds.minY + origin.y), proposal: .unspecified)
        }
    }

    /// The top left corner of every child and the size of the whole block.
    private func arrange(_ subviews: Subviews, maxWidth: CGFloat) -> (origins: [CGPoint], size: CGSize) {
        var origins: [CGPoint] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        var usedWidth: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > 0 && x + size.width > maxWidth {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            origins.append(CGPoint(x: x, y: y))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
            usedWidth = max(usedWidth, x - spacing)
        }
        return (origins, CGSize(width: usedWidth, height: y + rowHeight))
    }
}

#Preview {
    VStack(alignment: .leading, spacing: 24) {
        QuickReplyBar(options: ["Ja", "Nein"], isEnabled: true) { _ in }
        QuickReplyBar(options: ["Müll", "Schlagloch", "Straßenlaterne", "Spielgerät", "Graffiti", "Baum", "Etwas anderes"], isEnabled: true) { _ in }
    }
    .padding()
    .background(Color.black)
}
