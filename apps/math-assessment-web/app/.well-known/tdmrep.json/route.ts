const TDM_RESERVATION = {
  version: "1.0",
  policy: "reserved",
  owner: "서아인",
  contact: "ainssam@ai.cne.go.kr",
  scope: [
    "service code and design",
    "assessment selection and classification",
    "safe source transformations",
    "teacher-facing analysis and writing",
  ],
  note: "Text and data mining, model training, fine-tuning, and dataset construction are reserved. Public-source documents remain subject to their original publisher terms.",
};

export function GET() {
  return Response.json(TDM_RESERVATION, {
    headers: { "X-Robots-Tag": "noindex, nofollow, noarchive" },
  });
}
