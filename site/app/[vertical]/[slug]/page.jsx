import { marked } from "marked";

import { getPage, listPages, TRACKER_BASE } from "../../../lib/content";
import { articleJsonLd, breadcrumbJsonLd } from "../../../lib/jsonld";

export const dynamicParams = false;

export function generateStaticParams() {
  return listPages().map((p) => ({ vertical: p.vertical, slug: p.slug }));
}

export async function generateMetadata({ params }) {
  const { vertical, slug } = await params;
  const page = getPage(vertical, slug);
  return { title: page.title };
}

export default async function Page({ params }) {
  const { vertical, slug } = await params;
  const page = getPage(vertical, slug);
  const html = marked.parse(page.body);
  const jsonld = [articleJsonLd(page), breadcrumbJsonLd(page)];
  return (
    <article>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonld) }}
      />
      <h1>{page.title}</h1>
      {page.disclosures.map((d, i) => (
        <div className="disclosure" key={i}>
          {d}
        </div>
      ))}
      <div dangerouslySetInnerHTML={{ __html: html }} />
      {page.slots.map((slot) => (
        <p key={slot}>
          <a
            className="cta"
            href={`${TRACKER_BASE}/go/${slot}?page=${page.slug}`}
            rel="sponsored nofollow"
          >
            See today&apos;s best offer →
          </a>
        </p>
      ))}
      {page.related?.length > 0 && (
        <section>
          <h2>Related</h2>
          <ul className="pagelist">
            {page.related.map((r) => (
              <li key={r.slug}>
                <a href={`/${page.vertical}/${r.slug}/`}>{r.title}</a>
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
