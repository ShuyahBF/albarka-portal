import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Mail, Phone, Building } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import Documents from "@/pages/portal/Documents";
import Missions from "@/pages/portal/Missions";
import Echeances from "@/pages/portal/Echeances";
import { ClientReportsPanel } from "@/pages/admin/AdminReports";

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

  if (loading) return <div className="text-muted-foreground">Chargement…</div>;
  if (!client) return <div className="text-muted-foreground">Client introuvable.</div>;

  return (
    <div className="space-y-6" data-testid="admin-client-detail">
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

      <Tabs defaultValue="reports">
        <TabsList data-testid="client-detail-tabs">
          <TabsTrigger value="reports" data-testid="tab-client-reports">Rapports</TabsTrigger>
          <TabsTrigger value="documents" data-testid="tab-client-documents">Pièces</TabsTrigger>
          <TabsTrigger value="missions" data-testid="tab-client-missions">Missions</TabsTrigger>
          <TabsTrigger value="echeances" data-testid="tab-client-echeances">Échéances</TabsTrigger>
        </TabsList>
        <TabsContent value="reports" className="pt-4">
          <ClientReportsPanel tenantId={client.id} clientEmail={client.email} />
        </TabsContent>
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
