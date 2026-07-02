export function articleJsonLd(page) {
  return {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: page.title,
    articleSection: page.pageType,
    about: page.entity?.name || page.slug,
  };
}

export function breadcrumbJsonLd(page) {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: page.vertical, item: `/${page.vertical}/` },
      { "@type": "ListItem", position: 2, name: page.title },
    ],
  };
}
