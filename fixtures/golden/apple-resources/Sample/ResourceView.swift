import SwiftUI

struct ResourceView: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(String(localized: "screen_title"))
                .font(.system(size: 20, weight: .semibold))
                .foregroundStyle(Color("Accent"))
            Image("Hero")
                .frame(width: 120, height: 80)
                .scaledToFill()
            Image(systemName: "plus")
                .frame(width: 24, height: 24)
        }
        .padding(.horizontal, 20)
        .background(Color("Surface"))
        .cornerRadius(16)
    }
}
