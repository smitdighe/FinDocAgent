import { getJson, apiUrl } from "./client";
import type { FilingList, PageDetail } from "./types";

export function listFilings(signal?: AbortSignal): Promise<FilingList> {
  return getJson<FilingList>("/filings", signal);
}

export function getPageDetail(
  filingId: string,
  pageNo: number,
  signal?: AbortSignal,
): Promise<PageDetail> {
  return getJson<PageDetail>(`/filings/${filingId}/pages/${pageNo}`, signal);
}

/** Absolute URL for a page image (backend returns a relative image_url). */
export function pageImageUrl(filingId: string, pageNo: number): string {
  return apiUrl(`/filings/${filingId}/pages/${pageNo}/image`);
}
