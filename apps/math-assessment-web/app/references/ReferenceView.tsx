"use client";

import { useSearchParams } from "next/navigation";

import DesignExplorer from "./DesignExplorer";
import ReferenceExplorer from "./ReferenceExplorer";

export default function ReferenceView() {
  const query = useSearchParams();
  const legacy = query.get("view") === "categories" ||
    ["category", "curriculum", "subject", "region", "district"].some((key) => query.has(key));
  return legacy ? <ReferenceExplorer /> : <DesignExplorer />;
}
