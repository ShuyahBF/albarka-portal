import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Mail, Phone, Building, FileDown, Send } from "lucide-react";
import { apiClient, extractError, API } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import Documents from "@/pages/portal/Documents";
import Missions from "@/pages/portal/Missions";
import Echeances from "@/pages/portal/Echeances";

export default function AdminClientDetail() {
  const { id } = useParams();
  const [client, setClient] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await apiClient.get(`/clients/${id}`);
        setClient(data);
      } catch (err) {
        toast.error(extractError(err));
      } finally { setLoading(false); }
    })();
  }, [id]);

  const downloadReport = async () => {
    try {
      const token = localStorage.getItem("albarka_token");
      const res = await fetch(`${API}/reports/client/${id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Échec génération PDF");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `rapport-albarka-${(client.full_name || "client").replace(/\s+/g, "_")}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Rapport PDF téléchargé");
    } catch (err) {
      toast.error(err.message || "Erreur");
    }
  };

  if (loading) return <div className="text-muted-foreground">Chargement…</div>;
  if (!client) return <div className="text-muted-foreground">Client introuvable.</div>;

  return (
    <div className="space-y-6" data-testid="admin-client-detail">
      <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4">
        <div>
          <Link to="/admin/clients" className="text-sm text-muted-foreground hover:text-[#0F6B4A] flex items-center gap-1 mb-3" data-testid="back-to-clients">
            <ArrowLeft className="w-4 h-4" /> Retour aux clients
          </Link>
          <h1 className="font-display text-3xl md:text-4xl text-foreground">{client.full_name}</h1>
          <div className="flex flex-wrap gap-x-5 gap-y-1 mt-2 text-sm text-muted-foreground">
            <span className="flex items-center gap-1.5"><Mail className="w-3.5 h-3.5" />{client.email}</span>
            {client.company && <span className="flex items-center gap-1.5"><Building className="w-3.5 h-3.5" />{client.company}</span>}
            {client.phone && <span className="flex items-center gap-1.5"><Phone className="w-3.5 h-3.5" />{client.phone}</span>}
          </div>
        </div>
        <div className="flex gap-2">
          <Button
            onClick={downloadReport}
            className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white"
            data-testid="download-client-report-btn"
          >
            <FileDown className="w-4 h-4 mr-2" />
            Rapport PDF
          </Button>
        </div>
      </div>

      <Tabs defaultValue="documents">
        <TabsList data-testid="client-detail-tabs">
          <TabsTrigger value="documents" data-testid="tab-client-documents">Pièces</TabsTrigger>
          <TabsTrigger value="missions" data-testid="tab-client-missions">Missions</TabsTrigger>
          <TabsTrigger value="echeances" data-testid="tab-client-echeances">Échéances</TabsTrigger>
        </TabsList>
        <TabsContent value="documents" className="pt-4">
          <Documents tenantIdOverride={client.id} />
        </TabsContent>
        <TabsContent value="missions" className="pt-4">
          <Missions tenantIdOverride={client.id} staffMode />
        </TabsContent>
        <TabsContent value="echeances" className="pt-4">
          <Echeances tenantIdOverride={client.id} staffMode notifiable />
        </TabsContent>
      </Tabs>
    </div>
  );
}
