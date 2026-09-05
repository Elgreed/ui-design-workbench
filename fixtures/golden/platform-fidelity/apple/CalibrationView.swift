import SwiftUI

struct CalibrationView: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Platform sample")
                .font(.system(size: 20, weight: .semibold))
                .foregroundColor(.blue)
            HStack(spacing: 8) {
                Text("Nested text").font(.system(size: 14))
                Image(systemName: "star.fill").frame(width: 24, height: 24)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .frame(width: 240, height: 100)
            .background(.gray)
        }
        .padding(.leading, 24)
        .padding(.top, 16)
        .padding(.trailing, 40)
        .padding(.bottom, 32)
    }
}
