"use client";

import { useEffect, useMemo, useState } from "react";

import {
  fetchCatalog,
  type OfficialSourceRegistry,
  type SourceLayer,
} from "../lib/catalog-api";

const STATUS_LABELS: Record<string, string> = {
  official_landing_page_verified: "공식 게시 확인",
  official_current_index_verified: "현재 공식 목록 확인",
  official_search_index_verified: "공식 검색 목록 확인",
  collection_and_integrity_verified: "수집·무결성 확인",
};

export default function OfficialSources() {
  const [registry, setRegistry] = useState<OfficialSourceRegistry | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetchCatalog<OfficialSourceRegistry>("sources", controller.signal)
      .then(setRegistry)
      .catch((reason: Error) => {
        if (!controller.signal.aborted) setError(reason.message);
      });
    return () => controller.abort();
  }, []);

  const sourcesByLayer = useMemo(() => {
    if (!registry) return new Map<number, OfficialSourceRegistry["sources"]>();
    const groups = new Map<number, OfficialSourceRegistry["sources"]>();
    for (const source of registry.sources) {
      groups.set(source.layer, [...(groups.get(source.layer) ?? []), source]);
    }
    return groups;
  }, [registry]);

  if (error) {
    return (
      <div className="sourceRegistryError" role="alert">
        <strong>공식 출처를 불러오지 못했습니다.</strong>
        <p>{error}</p>
      </div>
    );
  }
  if (!registry) {
    return <div className="sourceRegistryLoading" role="status">공식 출처 체계를 확인하고 있습니다.</div>;
  }

  return (
    <section className="officialRegistry" aria-labelledby="official-registry-title">
      <div className="sectionLabel">
        <span className="stepPill">3</span>
        <div>
          <h2 id="official-registry-title">자료의 권위와 쓰임을 구분합니다</h2>
          <p>{registry.interpretation}</p>
        </div>
      </div>
      <div className="sourceLayerRail" aria-label="출처 권위 단계">
        {registry.layers.map((layer) => <LayerSummary key={layer.level} layer={layer} />)}
      </div>
      <div className="officialSourceGroups">
        {registry.layers.map((layer) => (
          <section key={layer.level} aria-labelledby={`source-layer-${layer.level}`}>
            <div className="officialSourceHeading">
              <span>0{layer.level}</span>
              <div><h3 id={`source-layer-${layer.level}`}>{layer.label}</h3><p>{layer.purpose}</p></div>
            </div>
            <ul>
              {(sourcesByLayer.get(layer.level) ?? []).map((source) => (
                <li key={source.source_id}>
                  <div className="officialSourceTopline">
                    <span>{source.curriculum} 개정</span>
                    <small>{STATUS_LABELS[source.verification_status] ?? source.verification_status}</small>
                  </div>
                  <h4>{source.title}</h4>
                  <dl>
                    <div><dt>발행</dt><dd>{source.provider}</dd></div>
                    <div><dt>식별자</dt><dd>{source.identifier}</dd></div>
                    <div><dt>서비스에서의 쓰임</dt><dd>{source.service_use}</dd></div>
                  </dl>
                  <div className="officialSourceFooter">
                    <p>{source.redistribution}</p>
                    <a href={source.url} target="_blank" rel="noreferrer">공식 자료 확인 <span aria-hidden="true">↗</span></a>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      <p className="registryVersion">검증일 {registry.verified_on} · 출처 레지스트리 {registry.schema_version}</p>
    </section>
  );
}

function LayerSummary({ layer }: { layer: SourceLayer }) {
  return (
    <div>
      <span>{layer.level}</span>
      <strong>{layer.label}</strong>
      <small>{layer.authority}</small>
    </div>
  );
}
