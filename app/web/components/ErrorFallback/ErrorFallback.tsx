import { Typography } from "@material-ui/core";
import Actions from "components/Actions";
import Button from "components/Button";
import ReportButton from "components/Navigation/ReportButton";
import PageTitle from "components/PageTitle";
import { useRouter } from "next/dist/client/router";
import Link from "next/link";
import { baseRoute } from "routes";
import makeStyles from "utils/makeStyles";

import {
  ERROR_HEADING,
  ERROR_INFO,
  ERROR_INFO_FATAL,
  GO_TO_HOMEPAGE,
  REFRESH_PAGE,
} from "./constants";

const useStyles = makeStyles((theme) => ({
  report: {
    marginTop: theme.spacing(2),
  },
}));

export default function ErrorFallback({ isFatal }: { isFatal?: boolean }) {
  const classes = useStyles();
  const router = useRouter();

  const handleRefresh = () => router.reload();

  return (
    <>
      <PageTitle>{ERROR_HEADING}</PageTitle>
      <Typography variant="body1">
        {isFatal ? ERROR_INFO_FATAL : ERROR_INFO}
      </Typography>
      {!isFatal && (
        <div className={classes.report}>
          <ReportButton isResponsive={false} />
        </div>
      )}

      <Actions>
        {!isFatal && (
          <Link href={baseRoute} passHref>
            <a>
              <Button variant="outlined">{GO_TO_HOMEPAGE}</Button>
            </a>
          </Link>
        )}

        <Button onClick={handleRefresh}>{REFRESH_PAGE}</Button>
      </Actions>
    </>
  );
}
