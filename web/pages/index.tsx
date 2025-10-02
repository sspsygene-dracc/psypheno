import { SearchBar } from "@/components/general/SearchBar";
import {
  SearchContextProvider,
  useSearchContext,
} from "@/context/SearchContext";
import { GeneInformationComponent } from "@/components/gv/GeneInformation";
import { VariantsList } from "@/components/gv/VariantsList";
import { GetServerSideProps } from "next";
import { queryToState, SearchPageProps } from "@/lib/queryToState";
import Head from "next/head";
import { Footer } from "@/components/general/Footer";

export const getServerSideProps: GetServerSideProps<SearchPageProps> = async (
  context
) => {
  return { props: queryToState(context) };
};

const IndexContent = () => {
  const searchContext = useSearchContext();
  const selectedGene = searchContext.searchState.selectedGene;

  return (
    <div className="flex flex-col min-h-screen">
      <SearchBar />
      <div className="flex flex-1 min-h-0">
        <div className="hidden md:flex md:w-1/3 lg:w-1/4">
          <GeneInformationComponent selectedGene={selectedGene} />
        </div>
        <div className="flex-1 md:w-2/3 lg:w-3/4">
          <VariantsList />
        </div>
      </div>
      <Footer />
    </div>
  );
};

export default function Index({
  initialGene,
  initialVariant,
  initialAssembly,
}: SearchPageProps) {
  return (
    <SearchContextProvider
      initialGene={initialGene}
      initialVariant={initialVariant}
      initialAssembly={initialAssembly}
    >
      <Head>
        <title>Varaico - Literature-Extracted Variants</title>
      </Head>
      <IndexContent />
    </SearchContextProvider>
  );
}
