// Display names and IDs follow docs/database.md. The group layout follows Meelyze's selection screen.
export type AllergenOption = {
  id: number;
  display_name: string;
  category: "required" | "recommended";
  display_order: number;
};

export const allergenOptions: AllergenOption[] = [
  { id: 1, display_name: "Egg", category: "required", display_order: 1 },
  { id: 2, display_name: "Milk", category: "required", display_order: 2 },
  { id: 3, display_name: "Wheat", category: "required", display_order: 3 },
  { id: 6, display_name: "Buckwheat", category: "required", display_order: 4 },
  { id: 7, display_name: "Peanut", category: "required", display_order: 5 },
  { id: 4, display_name: "Shrimp", category: "required", display_order: 6 },
  { id: 5, display_name: "Crab", category: "required", display_order: 7 },
  { id: 8, display_name: "Walnut", category: "required", display_order: 8 },
  { id: 11, display_name: "Cashew", category: "required", display_order: 9 },
  { id: 12, display_name: "Almond", category: "recommended", display_order: 10 },
  { id: 13, display_name: "Abalone", category: "recommended", display_order: 11 },
  { id: 14, display_name: "Squid", category: "recommended", display_order: 12 },
  { id: 15, display_name: "Salmon roe", category: "recommended", display_order: 13 },
  { id: 16, display_name: "Orange", category: "recommended", display_order: 14 },
  { id: 17, display_name: "Kiwi fruit", category: "recommended", display_order: 15 },
  { id: 18, display_name: "Beef", category: "recommended", display_order: 16 },
  { id: 10, display_name: "Sesame", category: "recommended", display_order: 17 },
  { id: 19, display_name: "Salmon", category: "recommended", display_order: 18 },
  { id: 20, display_name: "Mackerel", category: "recommended", display_order: 19 },
  { id: 9, display_name: "Soy", category: "recommended", display_order: 20 },
  { id: 21, display_name: "Chicken", category: "recommended", display_order: 21 },
  { id: 22, display_name: "Banana", category: "recommended", display_order: 22 },
  { id: 23, display_name: "Pork", category: "recommended", display_order: 23 },
  { id: 24, display_name: "Pistachio", category: "recommended", display_order: 24 },
  { id: 25, display_name: "Macadamia nut", category: "recommended", display_order: 25 },
  { id: 26, display_name: "Peach", category: "recommended", display_order: 26 },
  { id: 27, display_name: "Yam", category: "recommended", display_order: 27 },
  { id: 28, display_name: "Apple", category: "recommended", display_order: 28 },
  { id: 29, display_name: "Gelatin", category: "recommended", display_order: 29 },
];

