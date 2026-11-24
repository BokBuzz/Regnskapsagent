import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./lib/auth";
import BankPage from "./pages/BankPage";
import CompaniesPage from "./pages/CompaniesPage";
import CompanyLayout from "./pages/CompanyLayout";
import InboxPage from "./pages/InboxPage";
import LoginPage from "./pages/LoginPage";
import MfaPage from "./pages/MfaPage";
import ProposalPage from "./pages/ProposalPage";
import ReportPage from "./pages/ReportPage";
import UploadPage from "./pages/UploadPage";
import VatPage from "./pages/VatPage";
import VoucherPage from "./pages/VoucherPage";
import VouchersPage from "./pages/VouchersPage";

export default function App() {
  const { state } = useAuth();
  if (state.status === "loading") return <div className="center muted">Laster …</div>;
  if (state.status === "signed_out") return <LoginPage />;
  if (state.status === "needs_mfa_enroll" || state.status === "needs_mfa_verify") return <MfaPage />;
  return (
    <Routes>
      <Route path="/" element={<CompaniesPage />} />
      <Route path="/c/:cid" element={<CompanyLayout />}>
        <Route index element={<Navigate to="opplasting" replace />} />
        <Route path="opplasting" element={<UploadPage />} />
        <Route path="innboks" element={<InboxPage />} />
        <Route path="innboks/:pid" element={<ProposalPage />} />
        <Route path="bilag" element={<VouchersPage />} />
        <Route path="bilag/:vid" element={<VoucherPage />} />
        <Route path="bank" element={<BankPage />} />
        <Route path="rapport" element={<ReportPage />} />
        <Route path="mva" element={<VatPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
