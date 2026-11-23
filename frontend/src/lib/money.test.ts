import { formatDate, formatOre, parseKroner, vatAmount } from "./money";

test("formatOre", () => {
  expect(formatOre(123456)).toBe("1 234,56");
  expect(formatOre(-5)).toBe("−0,05");
  expect(formatOre(0)).toBe("0,00");
});

test("parseKroner", () => {
  expect(parseKroner("1 234,50")).toBe(123450);
  expect(parseKroner("625")).toBe(62500);
  expect(parseKroner("-12,5")).toBe(-1250);
  expect(parseKroner("12,345")).toBeNull();
  expect(parseKroner("abc")).toBeNull();
});

test("vatAmount matcher backend", () => {
  expect(vatAmount(10000, 2500)).toBe(2500);
  expect(vatAmount(2, 2500)).toBe(1);
  expect(vatAmount(-2, 2500)).toBe(-1);
  expect(vatAmount(333, 1200)).toBe(40);
});

test("formatDate", () => {
  expect(formatDate("2026-03-15")).toBe("15.03.2026");
});
