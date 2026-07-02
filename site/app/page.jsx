import Link from "next/link";

import { listPages } from "../lib/content";

export default function Home() {
  const pages = listPages();
  const byVertical = {};
  for (const p of pages) (byVertical[p.vertical] ||= []).push(p);
  return (
    <>
      <h1>Published pages</h1>
      {Object.entries(byVertical).map(([vertical, items]) => (
        <section key={vertical}>
          <h2>{vertical}</h2>
          <ul className="pagelist">
            {items.map((p) => (
              <li key={p.slug}>
                <Link href={`/${p.vertical}/${p.slug}/`}>{p.slug}</Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {pages.length === 0 && <p>No content yet — run `engine generate` first.</p>}
    </>
  );
}
