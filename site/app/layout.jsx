import "./globals.css";

export const metadata = {
  title: "affiliate-engine site",
  description: "Data-grounded pages published by affiliate-engine",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <main>{children}</main>
      </body>
    </html>
  );
}
