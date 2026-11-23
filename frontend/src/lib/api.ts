// Tynn klient mot Bokbuzz-API-et. Alle kall bærer innloggingstoken.

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

export type TokenSource = () => Promise<string | null>;

export interface Company {
  id: string;
  orgnr: string;
  name: string;
  role?: string;
  vat_registered: boolean;
  org_form: OrgForm;
  modules: Module[];
}

export type OrgForm = "ENK" | "AS";
export type Module = "taxi";

export interface NewCompany {
  orgnr: string;
  name: string;
  org_form: OrgForm;
  modules: Module[];
  vat_registered: boolean;
}

export interface DraftLine {
  account: string;
  amount_ore: number;
  vat_code?: string | null;
  vat_amount_ore?: number | null;
  description?: string | null;
}

export interface VoucherDraft {
  voucher_date: string;
  description: string;
  lines: DraftLine[];
}

export interface Finding {
  code: string;
  message: string;
}

export interface DocumentRow {
  id: string;
  original_filename: string | null;
  mime_type: string;
  status: string;
  created_at: string;
}

export interface Proposal {
  id: string;
  document_id: string;
  status: "pending" | "approved" | "rejected" | "needs_manual";
  model: string | null;
  draft: VoucherDraft | null;
  extraction: { supplier_name?: string | null; supplier_orgnr?: string | null; total_amount_ore?: number } | null;
  validation_errors: Finding[];
  warnings: Finding[];
  escalated: boolean;
  created_at: string;
  voucher_id: string | null;
  document?: DocumentRow;
}

export interface PostingLine {
  line_no: number;
  account: string;
  amount_ore: number;
  vat_code: string | null;
  vat_base_line_no: number | null;
  description: string | null;
}

export interface Voucher {
  id: string;
  year: number;
  series: string;
  number: number;
  voucher_date: string;
  description: string;
  document_id: string | null;
  reverses_voucher_id: string | null;
  lines?: PostingLine[];
}

export interface Account {
  number: string;
  name: string;
  account_type: string;
  default_vat_code: string | null;
}

export interface Entity {
  orgnr: string;
  name: string;
  org_form: string;
  vat_registered: boolean;
  deleted: boolean;
  address: string | null;
}

export interface VatCode {
  code: string;
  description: string;
  direction: "input" | "output" | "none";
  rate_bp: number;
}

export class Api {
  constructor(private baseUrl: string, private token: TokenSource) {}

  private async request<T>(method: string, path: string, body?: unknown, form?: FormData): Promise<T> {
    const token = await this.token();
    const headers: Record<string, string> = {};
    if (token) headers.authorization = `Bearer ${token}`;
    if (body !== undefined) headers["content-type"] = "application/json";
    let resp: Response;
    try {
      resp = await fetch(this.baseUrl + path, {
        method,
        headers,
        body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
      });
    } catch {
      throw new ApiError(0, "network", "Får ikke kontakt med Bokbuzz. Sjekk nettforbindelsen.");
    }
    if (!resp.ok) {
      let code = "error";
      let message = `Noe gikk galt (${resp.status})`;
      try {
        const data = await resp.json();
        const err = data.detail && typeof data.detail === "object" ? data.detail : data;
        code = err.error ?? code;
        if (typeof err.message === "string") message = err.message;
        else if (Array.isArray(data.detail)) message = "Noen felt er ugyldige";
      } catch {
        /* ikke JSON */
      }
      throw new ApiError(resp.status, code, message);
    }
    return (await resp.json()) as T;
  }

  vatCodes = (on?: string) => this.request<VatCode[]>("GET", `/vat-codes${on ? `?on=${on}` : ""}`);
  me = () => this.request<{ user_id: string; mfa: boolean }>("GET", "/me");
  companies = () => this.request<Company[]>("GET", "/companies");
  lookup = (orgnr: string) => this.request<Entity>("GET", `/lookup/orgnr/${encodeURIComponent(orgnr)}`);
  createCompany = (c: NewCompany) => this.request<Company>("POST", "/companies", c);
  company = (cid: string) => this.request<Company>("GET", `/companies/${cid}`);
  accounts = (cid: string) => this.request<Account[]>("GET", `/companies/${cid}/accounts`);

  upload = (cid: string, file: File) => {
    const form = new FormData();
    form.append("file", file, file.name);
    return this.request<DocumentRow & { duplicate: boolean }>("POST", `/companies/${cid}/documents`, undefined, form);
  };
  documents = (cid: string) => this.request<DocumentRow[]>("GET", `/companies/${cid}/documents`);

  async documentBlob(cid: string, documentId: string): Promise<Blob> {
    const token = await this.token();
    const resp = await fetch(`${this.baseUrl}/companies/${cid}/documents/${documentId}/content`, {
      headers: token ? { authorization: `Bearer ${token}` } : {},
    });
    if (!resp.ok) throw new ApiError(resp.status, "error", "Kunne ikke hente bilaget");
    return resp.blob();
  }

  proposals = (cid: string, status = "pending") =>
    this.request<Proposal[]>("GET", `/companies/${cid}/proposals?status=${status}`);
  proposal = (cid: string, pid: string) => this.request<Proposal>("GET", `/companies/${cid}/proposals/${pid}`);
  openReview = (cid: string, pid: string) =>
    this.request<{ review_token: string; expires_at: string }>("POST", `/companies/${cid}/proposals/${pid}/review`);
  approve = (cid: string, pid: string, reviewToken: string, corrected?: VoucherDraft) =>
    this.request<Voucher>("POST", `/companies/${cid}/proposals/${pid}/approve`, {
      review_token: reviewToken,
      confirm: true,
      corrected_draft: corrected ?? null,
    });
  reject = (cid: string, pid: string, reason: string) =>
    this.request<Proposal>("POST", `/companies/${cid}/proposals/${pid}/reject`, { reason });

  vouchers = (cid: string, year?: number) =>
    this.request<Voucher[]>("GET", `/companies/${cid}/vouchers${year ? `?year=${year}` : ""}`);
  voucher = (cid: string, vid: string) => this.request<Voucher>("GET", `/companies/${cid}/vouchers/${vid}`);
  reverse = (cid: string, vid: string, reason: string) =>
    this.request<Voucher>("POST", `/companies/${cid}/vouchers/${vid}/reverse`, { reason, confirm: true });
  trialBalance = (cid: string, from: string, to: string) =>
    this.request<{ accounts: { account: string; name: string; balance_ore: number }[]; total_ore: number }>(
      "GET",
      `/companies/${cid}/reports/trial-balance?from=${from}&to=${to}`,
    );
}
