import type { AnchorHTMLAttributes } from "react";

type SiteLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  href: string;
};

/**
 * Use a normal document navigation for internal links.
 *
 * The production deployment joins a Next.js frontend and FastAPI service
 * through Vercel service rewrites.  RSC prefetch requests are not preserved by
 * that boundary, while ordinary document requests are.  A plain anchor avoids
 * noisy 404 prefetches and guarantees that every teacher-facing menu works.
 */
export default function SiteLink({ href, ...props }: SiteLinkProps) {
  return <a href={href} {...props} />;
}
