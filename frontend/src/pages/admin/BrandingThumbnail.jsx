import React, { useEffect, useState } from "react";
import { Image as ImageIcon } from "lucide-react";
import { API } from "@/lib/api";

/** Auth-fetched thumbnail. Refreshes when `key` changes (e.g. path/uploaded_at). */
export default function BrandingThumbnail({ kind, refreshKey, className = "" }) {
  const [url, setUrl] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let revoked = null;
    let alive = true;
    (async () => {
      setError(false);
      try {
        const token = localStorage.getItem("albarka_token");
        const res = await fetch(`${API}/admin/branding/${kind}/preview`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error(String(res.status));
        const blob = await res.blob();
        const u = URL.createObjectURL(blob);
        revoked = u;
        if (alive) setUrl(u);
      } catch {
        if (alive) setError(true);
      }
    })();
    return () => {
      alive = false;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [kind, refreshKey]);

  if (error || !url) {
    return (
      <div className={`bg-slate-100 flex items-center justify-center text-slate-400 ${className}`}>
        <ImageIcon className="w-6 h-6" />
      </div>
    );
  }
  return (
    <img
      src={url}
      alt={kind}
      className={`object-contain bg-slate-50 border rounded-md ${className}`}
      data-testid={`branding-thumb-${kind}`}
    />
  );
}
