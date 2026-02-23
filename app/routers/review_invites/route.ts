import { NextRequest, NextResponse } from "next/server";
import { API_BASE_URL } from "@/lib/config";

function getBackendSessionCookie(req: NextRequest) {
  // Stored as: "enginuity_auth%3D<jwt>"
  const v = req.cookies.get("backend_session")?.value || "";
  return v ? decodeURIComponent(v) : "";
}

export async function POST(req: NextRequest) {
  const cookiePair = getBackendSessionCookie(req);
  if (!cookiePair) {
    return NextResponse.json({ detail: "UNAUTHENTICATED" }, { status: 401 });
  }

  const res = await fetch(`${API_BASE_URL}/professional/review-invites`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      Cookie: cookiePair, // "enginuity_auth=<jwt>"
    },
    cache: "no-store",
  });

  const text = await res.text();
  return new NextResponse(text || "", {
    status: res.status,
    headers: {
      "Content-Type": res.headers.get("content-type") ?? "application/json",
    },
  });
}