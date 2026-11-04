//
//  ImagePreparation.swift
//  Ortsbild
//

import UIKit

extension UIImage {
    /// JPEG for the upload: upright pixels, at most `maxSide` points on the long side, no metadata.
    ///
    /// The server only accepts what it can check, and a JPEG from here settles the HEIC question.
    /// Redrawing turns the orientation flag into real pixels and leaves the location and device data behind.
    func jpegForUpload(maxSide: CGFloat = 2560, quality: CGFloat = 0.85) -> Data? {
        let longest = max(size.width, size.height)
        guard longest > 0 else { return nil }
        let scale = min(1, maxSide / longest)
        let target = CGSize(width: (size.width * scale).rounded(), height: (size.height * scale).rounded())

        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = true
        let renderer = UIGraphicsImageRenderer(size: target, format: format)
        return renderer.jpegData(withCompressionQuality: quality) { _ in
            draw(in: CGRect(origin: .zero, size: target))
        }
    }
}
