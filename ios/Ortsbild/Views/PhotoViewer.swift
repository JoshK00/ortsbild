//
//  PhotoViewer.swift
//  Ortsbild
//

import SwiftUI
import UIKit

/// The photo of a draft in full screen, so the user can check it before the release: a small face or a plate is hard to see in the
/// thumbnail. Pinch to zoom, double tap to zoom in and out, the close button is 44 pt.
struct PhotoViewer: View {
    let image: UIImage
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack(alignment: .topTrailing) {
            Color.black.ignoresSafeArea()
            ZoomableImage(image: image)
                .ignoresSafeArea()

            Button {
                dismiss()
            } label: {
                Image(systemName: "xmark")
                    .font(.headline)
                    .foregroundStyle(.white)
                    .frame(width: 44, height: 44)
                    .background(.black.opacity(0.55), in: Circle())
                    .overlay(Circle().strokeBorder(.white.opacity(0.4), lineWidth: 1))
            }
            .padding(.top, 8)
            .padding(.trailing, 16)
            .accessibilityLabel("Schließen")
        }
        .overlay(alignment: .bottom) {
            Text("Prüfe das Bild: mit zwei Fingern vergrößern, zweimal tippen zoomt.")
                .font(.footnote)
                .foregroundStyle(.white.opacity(0.85))
                .multilineTextAlignment(.center)
                .padding(.horizontal, 24)
                .padding(.vertical, 10)
                .background(.black.opacity(0.55), in: Capsule())
                .padding(.bottom, 12)
                .accessibilityHidden(true)
        }
        .preferredColorScheme(.dark)
        .accessibilityAction(.escape) { dismiss() }
    }
}

/// An image in a `UIScrollView`: pinch zoom up to 5x and double tap. It starts fitted to the screen.
private struct ZoomableImage: UIViewRepresentable {
    let image: UIImage

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> ZoomScrollView {
        let scrollView = ZoomScrollView(image: image)
        scrollView.delegate = context.coordinator
        context.coordinator.scrollView = scrollView

        let doubleTap = UITapGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.doubleTapped(_:)))
        doubleTap.numberOfTapsRequired = 2
        scrollView.addGestureRecognizer(doubleTap)

        scrollView.isAccessibilityElement = true
        scrollView.accessibilityLabel = "Foto prüfen, Vollbild"
        scrollView.accessibilityTraits = .image
        return scrollView
    }

    func updateUIView(_ scrollView: ZoomScrollView, context: Context) {}

    final class Coordinator: NSObject, UIScrollViewDelegate {
        weak var scrollView: ZoomScrollView?

        func viewForZooming(in scrollView: UIScrollView) -> UIView? { (scrollView as? ZoomScrollView)?.imageView }

        @objc func doubleTapped(_ gesture: UITapGestureRecognizer) {
            guard let scrollView, let imageView = scrollView.imageView else { return }
            if scrollView.zoomScale > 1 {
                scrollView.setZoomScale(1, animated: true)
            } else {
                // Zoom in on the point that was tapped
                let point = gesture.location(in: imageView)
                let scale: CGFloat = 3
                let size = CGSize(width: scrollView.bounds.width / scale, height: scrollView.bounds.height / scale)
                scrollView.zoom(to: CGRect(x: point.x - size.width / 2, y: point.y - size.height / 2, width: size.width, height: size.height), animated: true)
            }
        }
    }
}

/// Keeps the image as large as the screen while it is not zoomed, also after a rotation.
private final class ZoomScrollView: UIScrollView {
    private(set) var imageView: UIImageView?

    init(image: UIImage) {
        super.init(frame: .zero)
        let imageView = UIImageView(image: image)
        imageView.contentMode = .scaleAspectFit
        addSubview(imageView)
        self.imageView = imageView
        minimumZoomScale = 1
        maximumZoomScale = 5
        showsHorizontalScrollIndicator = false
        showsVerticalScrollIndicator = false
        contentInsetAdjustmentBehavior = .never
        backgroundColor = .clear
    }

    @available(*, unavailable) required init?(coder: NSCoder) { fatalError("not used") }

    override func layoutSubviews() {
        super.layoutSubviews()
        if zoomScale == 1 {
            imageView?.frame = bounds
            contentSize = bounds.size
        }
    }
}
