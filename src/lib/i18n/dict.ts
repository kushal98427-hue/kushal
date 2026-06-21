export type Lang = "np" | "en";

export const LANGS: Lang[] = ["np", "en"];
export const DEFAULT_LANG: Lang = "np";

export const dict = {
  np: {
    appName: "उधारो रजिस्टर",
    tagline: "तपाईंको पसलको साथी",

    nav: {
      dashboard: "ड्यासबोर्ड",
      customers: "ग्राहक",
      settings: "सेटिङ",
    },

    auth: {
      login: "लग इन",
      signup: "खाता खोल्नुहोस्",
      phone: "मोबाइल नम्बर",
      phoneHint: "उदाहरण: 9851234567",
      password: "पासवर्ड",
      passwordHint: "कम्तीमा ६ अक्षर",
      shopName: "पसलको नाम",
      submitLogin: "लग इन गर्नुहोस्",
      submitSignup: "खाता खोल्नुहोस्",
      switchToSignup: "नयाँ हुनुहुन्छ? खाता खोल्नुहोस्",
      switchToLogin: "पहिले नै खाता छ? लग इन गर्नुहोस्",
      logout: "लग आउट",
      errorInvalid: "मोबाइल नम्बर वा पासवर्ड मिलेन।",
      errorGeneric: "केही गडबड भयो। फेरि कोशिश गर्नुहोस्।",
    },

    dashboard: {
      title: "ड्यासबोर्ड",
      totalReceivable: "जम्मा उठाउनुपर्ने",
      customers: "ग्राहक",
      entriesToday: "आजका कारोबार",
      noEntriesYet: "अहिलेसम्म कुनै कारोबार छैन।",
      recentActivity: "हालका कारोबार",
      addFirstCustomer: "पहिलो ग्राहक थप्नुहोस्",
    },

    customers: {
      title: "ग्राहक",
      add: "नयाँ ग्राहक",
      search: "नामले खोज्नुहोस्",
      none: "कुनै ग्राहक छैन।",
      name: "नाम",
      phone: "मोबाइल नम्बर (वैकल्पिक)",
      note: "टिप्पणी (वैकल्पिक)",
      save: "सुरक्षित गर्नुहोस्",
      saving: "सुरक्षित हुँदै…",
      balance: "बाँकी",
      due: "उधारो",
      paid: "भुक्तानी",
      addedOn: "थपिएको",
      noEntries: "यो ग्राहकको कुनै कारोबार छैन।",
    },

    entries: {
      add: "नयाँ कारोबार",
      kind: "कारोबारको प्रकार",
      udharo: "उधारो दिएँ",
      payment: "भुक्तानी पाएँ",
      amount: "रकम",
      date: "मिति",
      note: "टिप्पणी (वैकल्पिक)",
      save: "सुरक्षित गर्नुहोस्",
      delete: "मेटाउनुहोस्",
      confirmDelete: "के पक्का मेटाउने?",
    },

    settings: {
      title: "सेटिङ",
      language: "भाषा",
      nepali: "नेपाली",
      english: "English",
      account: "खाता",
    },

    common: {
      back: "फिर्ता",
      cancel: "रद्द गर्नुहोस्",
      currency: "रु",
      loading: "लोड हुँदै…",
    },
  },

  en: {
    appName: "Udharo Register",
    tagline: "Your shop's companion",

    nav: {
      dashboard: "Dashboard",
      customers: "Customers",
      settings: "Settings",
    },

    auth: {
      login: "Log in",
      signup: "Create account",
      phone: "Mobile number",
      phoneHint: "Example: 9851234567",
      password: "Password",
      passwordHint: "At least 6 characters",
      shopName: "Shop name",
      submitLogin: "Log in",
      submitSignup: "Create account",
      switchToSignup: "New here? Create an account",
      switchToLogin: "Already have an account? Log in",
      logout: "Log out",
      errorInvalid: "Wrong mobile number or password.",
      errorGeneric: "Something went wrong. Please try again.",
    },

    dashboard: {
      title: "Dashboard",
      totalReceivable: "Total receivable",
      customers: "Customers",
      entriesToday: "Today's entries",
      noEntriesYet: "No entries yet.",
      recentActivity: "Recent activity",
      addFirstCustomer: "Add your first customer",
    },

    customers: {
      title: "Customers",
      add: "New customer",
      search: "Search by name",
      none: "No customers yet.",
      name: "Name",
      phone: "Mobile number (optional)",
      note: "Note (optional)",
      save: "Save",
      saving: "Saving…",
      balance: "Balance",
      due: "Udharo",
      paid: "Payment",
      addedOn: "Added on",
      noEntries: "No entries for this customer.",
    },

    entries: {
      add: "New entry",
      kind: "Entry type",
      udharo: "Gave udharo",
      payment: "Received payment",
      amount: "Amount",
      date: "Date",
      note: "Note (optional)",
      save: "Save",
      delete: "Delete",
      confirmDelete: "Delete this entry?",
    },

    settings: {
      title: "Settings",
      language: "Language",
      nepali: "नेपाली",
      english: "English",
      account: "Account",
    },

    common: {
      back: "Back",
      cancel: "Cancel",
      currency: "Rs",
      loading: "Loading…",
    },
  },
} as const;

export type Dict = (typeof dict)[Lang];
